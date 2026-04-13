from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import AsyncGenerator

import anthropic
from dotenv import load_dotenv

load_dotenv()

from tools import TOOL_SCHEMAS, format_images_for_claude, get_page_images, search_manual, summarize_search_result

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 4096
MAX_ROUNDS = 6

SYSTEM_PROMPT = """You are the Vulcan OmniPro 220 assistant — a hands-on technical advisor for this Harbor Freight multiprocess welder. The person asking just bought this machine and is in their garage trying to get it running. They're capable but not a professional welder.

## How to respond

1. **Search results are already loaded.** The manual pages most relevant to this question are already in the conversation. Read them before anything else. Only call search_manual again if you need to look up a completely different topic.
2. **Fetch page images only when the text isn't enough** — e.g. when a snippet says "see figure" or the question is specifically about wiring connections or a visual chart. Skip it if the text already has the numbers.
3. **Show, don't just tell.** Generate a visual artifact for anything that's hard to explain in words. This matters more than anything else.
4. **Use real numbers.** Amps, volts, IPM, CFH — not "adjust as needed."
5. **Cite the page.** End every answer with: *Source: [Manual Name], Page [N]*

## Artifacts

Wrap visual content in these tags — the UI renders them separately:

```
<artifact type="TYPE" title="TITLE">
CONTENT
</artifact>
```

**`type="html"`** — interactive calculators and settings tables
- Self-contained HTML with inline CSS + JS
- Dark bg (#111318), orange accent (#e8924a)
- Add at the bottom: `<script>window.addEventListener('load',()=>parent.postMessage({type:'resize',height:document.body.scrollHeight+32},'*'))</script>`

**`type="svg"`** — wiring and polarity diagrams
- Color-coded cables: red = positive/electrode, black = negative/ground, yellow = gas
- Label every connector to match the actual machine panel
- `width="100%" height="auto"` with a viewBox
- Dark background rect: `fill="#1a1a2e"`

**`type="mermaid"`** — troubleshooting flowcharts
- `flowchart TD` for diagnosis trees, `flowchart LR` for setup steps
- Short node labels, descriptive edge labels
- Valid Mermaid syntax only

For manual pages with relevant diagrams, add a reference tag:
`<manual-image pdf="owner-manual" page="5" caption="Duty cycle chart" />`
The UI shows a clickable thumbnail.

## Polarity quick reference

- MIG solid wire → DCEP
- Flux-cored self-shielded → DCEN
- Flux-cored gas-shielded → DCEP
- TIG steel/stainless → DCEN, TIG aluminum → AC
- Stick 6010/7018 → DCEP, 6011/6013 → DCEP or AC

Always state both amperage AND input voltage when discussing duty cycle. 120V and 240V are very different.

## When user uploads a weld photo

1. Search for weld diagnosis / weld quality pages
2. Fetch those page images
3. Identify the defect (porosity, undercut, spatter, burn-through, cold lap, cracks)
4. List causes by likelihood
5. Generate a `type="mermaid"` diagnostic flowchart
6. Add `<manual-image />` tags for relevant pages
"""

_ARTIFACT_PARSE = re.compile(
    r'<artifact\s+type="([^"]*)"\s+title="([^"]*)"\s*>(.*?)</artifact>',
    re.DOTALL,
)
_MANUAL_IMG_PARSE = re.compile(
    r'<manual-image\s+pdf="([^"]*)"\s+page="(\d+)"(?:\s+caption="([^"]*)")?\s*/?>',
)


class WeldingAgent:
    def __init__(self):
        self.client = anthropic.AsyncAnthropic()
        self._histories: dict[str, list] = {}

    def clear_session(self, session_id: str):
        self._histories.pop(session_id, None)

    async def stream_response(
        self,
        user_message: str,
        session_id: str = "default",
        user_images: list[dict] | None = None,
    ) -> AsyncGenerator[dict, None]:
        history = self._histories.setdefault(session_id, [])

        # Pre-run the search before hitting the API — saves a full round-trip
        query = user_message[:300]
        yield {"event": "tool_start", "data": {"name": "search_manual", "input": {"query": query}}}
        results = search_manual(query, top_k=3)
        yield {"event": "tool_result", "data": {"name": "search_manual", "summary": summarize_search_result(results)}}

        tid = f"toolu_{uuid.uuid4().hex[:24]}"
        user_content = _build_user_content(user_message, user_images)

        history.append({"role": "user", "content": user_content})
        history.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": tid, "name": "search_manual", "input": {"query": query, "top_k": 3}},
        ]})
        history.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tid, "content": json.dumps(results)},
        ]})

        try:
            async for event in self._loop(history):
                yield event
        except Exception as exc:
            logger.exception("Agent error: %s", exc)
            yield {"event": "error", "data": {"message": str(exc)}}
        finally:
            if len(history) > 40:
                self._histories[session_id] = history[-40:]

    async def _loop(self, history: list) -> AsyncGenerator[dict, None]:
        for _ in range(MAX_ROUNDS):
            full_text = ""
            tool_uses: list[dict] = []
            current_tool: dict | None = None

            # retry on rate limit
            for attempt in range(3):
                try:
                    stream_ctx = self.client.messages.stream(
                        model=MODEL,
                        max_tokens=MAX_TOKENS,
                        system=SYSTEM_PROMPT,
                        tools=TOOL_SCHEMAS,
                        messages=history,
                    )
                    break
                except anthropic.RateLimitError:
                    if attempt == 2:
                        raise
                    wait = 15 * (2 ** attempt)
                    logger.warning("Rate limited — retrying in %ds", wait)
                    await asyncio.sleep(wait)

            async with stream_ctx as stream:
                async for ev in stream:
                    if ev.type == "content_block_start":
                        if ev.content_block.type == "tool_use":
                            current_tool = {"id": ev.content_block.id, "name": ev.content_block.name, "input_json": ""}

                    elif ev.type == "content_block_delta":
                        if hasattr(ev.delta, "text"):
                            full_text += ev.delta.text
                            yield {"event": "text_delta", "data": {"chunk": ev.delta.text}}
                        elif hasattr(ev.delta, "partial_json") and current_tool:
                            current_tool["input_json"] += ev.delta.partial_json

                    elif ev.type == "content_block_stop" and current_tool:
                        try:
                            current_tool["input"] = json.loads(current_tool["input_json"] or "{}")
                        except json.JSONDecodeError:
                            current_tool["input"] = {}
                        tool_uses.append(current_tool)
                        current_tool = None

                final = await stream.get_final_message()
                stop_reason = final.stop_reason

            history.append({"role": "assistant", "content": final.content})

            if stop_reason == "end_turn":
                for ev in _parse_artifacts(full_text):
                    yield ev
                for ev in _parse_manual_images(full_text):
                    yield ev
                break

            if stop_reason == "tool_use":
                if full_text.strip():
                    yield {"event": "clear_text", "data": {}}

                tool_results = []
                for tool in tool_uses:
                    name, inp = tool["name"], tool["input"]
                    yield {"event": "tool_start", "data": {"name": name, "input": inp}}

                    if name == "search_manual":
                        res = search_manual(**inp)
                        content = json.dumps(res)
                        summary = summarize_search_result(res)
                    elif name == "get_page_images":
                        res = get_page_images(**inp)
                        content = format_images_for_claude(res)
                        summary = f"Fetched {len(res)} page image(s)"
                    else:
                        content = json.dumps({"error": f"unknown tool: {name}"})
                        summary = f"Unknown tool: {name}"

                    yield {"event": "tool_result", "data": {"name": name, "summary": summary}}
                    tool_results.append({"type": "tool_result", "tool_use_id": tool["id"], "content": content})

                history.append({"role": "user", "content": tool_results})
                continue

            break

        yield {"event": "done", "data": {}}


def _build_user_content(text: str, images: list[dict] | None) -> list | str:
    if not images:
        return text
    content = []
    for img in images:
        content.append({"type": "image", "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]}})
    content.append({"type": "text", "text": text})
    return content


def _parse_artifacts(text: str):
    for m in _ARTIFACT_PARSE.finditer(text):
        yield {"event": "artifact", "data": {"type": m.group(1), "title": m.group(2), "content": m.group(3).strip()}}


def _parse_manual_images(text: str):
    for m in _MANUAL_IMG_PARSE.finditer(text):
        yield {"event": "manual_image", "data": {"pdf": m.group(1), "page": int(m.group(2)), "caption": m.group(3) or ""}}


_agent: WeldingAgent | None = None


def get_agent() -> WeldingAgent:
    global _agent
    if _agent is None:
        _agent = WeldingAgent()
    return _agent
