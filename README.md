# Vulcan OmniPro 220 Assistant

A multimodal welding assistant built on the Claude Agent SDK. Ask it anything about the OmniPro 220 and it answers with actual visuals — wiring diagrams, interactive calculators, troubleshooting flowcharts — not just text.

<img src="product.webp" alt="Vulcan OmniPro 220" width="380" /> <img src="product-inside.webp" alt="Inside panel" width="380" />

## Getting started

```bash
git clone https://github.com/karthikosa11/prox-challenge.git
cd prox-challenge
cp .env.example .env        # paste your Anthropic API key
uv sync
uv run python main.py
```

Open http://localhost:8000. First run preprocesses the PDFs automatically (~30 seconds).

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

## How it works

The owner's manual is 48 pages of dense content — duty cycle tables, polarity diagrams, wiring schematics, troubleshooting matrices. A lot of the critical information lives in images, not text. The agent is built to handle that.

**Knowledge extraction**

On startup, `preprocess.py` converts every page of all three PDFs (owner manual, quick-start guide, selection chart) into PNG images and extracts the text. Pages get classified as text-heavy, diagram-heavy, or mixed. Everything gets indexed with TF-IDF so the agent can find relevant pages quickly.

**Search and retrieval**

When you ask a question, the agent runs a TF-IDF search before hitting the API. The top matching pages get pre-loaded into the conversation context. If any of those pages are diagrams, the agent fetches the actual images and sends them to Claude as vision inputs — so Claude is literally reading the wiring schematic, not just a text description of it.

**Artifact generation**

The agent generates visual responses using the Claude artifacts pattern:

- Polarity or wiring questions → SVG diagram showing which cable goes in which socket
- Duty cycle questions → interactive HTML calculator with a slider
- Troubleshooting questions → Mermaid flowchart walking through the diagnosis
- Settings questions → HTML configurator (process + material + thickness → wire speed + voltage)

These render inline in the chat — not as attachments or links.

**Agent loop**

Built on the Anthropic Claude SDK with streaming tool use. The loop runs up to 6 rounds, streaming text to the UI as it arrives. Tool calls (search, image fetch) show up as status events so you can see what the agent is doing. History is trimmed to the last 40 messages to keep context manageable.

## Stack

Python, FastAPI, uvicorn, anthropic SDK, pymupdf, scikit-learn. Frontend is vanilla JS with Tailwind and Mermaid loaded from CDN — no build step needed.

## Questions it handles well

- "What's the duty cycle for MIG at 200A on 240V?"
- "Show me the polarity wiring for TIG"
- "I'm getting porosity in my flux-cored welds, what should I check?"
- "What wire speed and voltage should I use for 1/4 inch steel MIG?"
- Upload a photo of a bad weld → defect diagnosis

## Project structure

```
main.py          FastAPI server
agent.py         Claude agentic loop, streaming, artifact parsing
tools.py         search_manual() and get_page_images() tool implementations
preprocess.py    PDF to PNG conversion and TF-IDF index building
static/          index.html + app.js (chat UI)
files/           Owner manual, quick-start guide, selection chart PDFs
```
