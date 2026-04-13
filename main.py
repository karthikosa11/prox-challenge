from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not (DATA_DIR / "index.json").exists():
        logger.info("First run — converting PDFs to images and building search index (~60s)")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _build_index)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _warm_index)
    yield


app = FastAPI(title="OmniPro 220 Assistant", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _build_index():
    from preprocess import build_index
    build_index(force=False)
    logger.info("Index ready.")


def _warm_index():
    from tools import _ensure_index
    _ensure_index()


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/image/{pdf_name}/{page_num}")
async def serve_page_image(pdf_name: str, page_num: int):
    allowed = {"owner-manual", "quick-start-guide", "selection-chart"}
    if pdf_name not in allowed:
        raise HTTPException(status_code=404, detail="Unknown PDF")

    pages_dir = DATA_DIR / "pages" / pdf_name
    for ext in (".jpg", ".jpeg", ".png"):
        p = pages_dir / f"page_{page_num - 1}{ext}"
        if p.exists():
            mime = "image/jpeg" if ext != ".png" else "image/png"
            return FileResponse(str(p), media_type=mime, headers={"Cache-Control": "public, max-age=86400"})

    raise HTTPException(status_code=404, detail=f"Page not found: {pdf_name} p{page_num}")


@app.post("/api/chat")
async def chat(
    message: str = Form(default=""),
    session_id: str = Form(default="default"),
    images: list[UploadFile] = File(default=[]),
):
    from agent import get_agent

    if not message.strip() and not images:
        raise HTTPException(status_code=400, detail="Message or image required")

    user_images = []
    for f in images:
        raw = await f.read()
        user_images.append({"data": base64.b64encode(raw).decode(), "media_type": f.content_type or "image/jpeg"})

    agent = get_agent()

    async def events():
        try:
            async for ev in agent.stream_response(message, session_id, user_images or None):
                yield {"event": ev["event"], "data": json.dumps(ev["data"], ensure_ascii=False)}
        except Exception as exc:
            logger.exception("Stream error: %s", exc)
            yield {"event": "error", "data": json.dumps({"message": str(exc)})}

    return EventSourceResponse(events())


@app.post("/api/clear")
async def clear_session(session_id: str = Form(default="default")):
    from agent import get_agent
    get_agent().clear_session(session_id)
    return {"ok": True}


if __name__ == "__main__":
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("\nANTHROPIC_API_KEY not set — copy .env.example to .env and add your key.\n")

    print("\n  OmniPro 220 Assistant: http://localhost:8000\n")

    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False, log_level="info")
