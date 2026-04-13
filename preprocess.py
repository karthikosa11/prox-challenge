from __future__ import annotations

import base64
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

import fitz
from PIL import Image

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
FILES_DIR = BASE_DIR / "files"
DATA_DIR = BASE_DIR / "data"
PAGES_DIR = DATA_DIR / "pages"
INDEX_PATH = DATA_DIR / "index.json"

PDF_NAMES = ["owner-manual", "quick-start-guide", "selection-chart"]

PDF_DISPLAY = {
    "owner-manual": "Owner's Manual",
    "quick-start-guide": "Quick-Start Guide",
    "selection-chart": "Process Selection Chart",
}

STOPWORDS = {
    "the","a","an","and","or","but","in","on","at","to","for","of","with","by",
    "from","is","are","be","this","that","it","as","not","do","if","so","up",
    "use","used","using","will","can","may","should","must","when","then",
    "which","than","more","all","also","only","any","into","out","no","each",
    "see","set","your","you","before","after","during","while",
}


@dataclass
class PageRecord:
    pdf: str
    page: int
    text: str
    page_type: str
    keywords: list[str]
    image_path: str


def _classify(text: str) -> str:
    n = len(text.split())
    if n >= 80:
        return "text"
    if n <= 25:
        return "diagram"
    return "mixed"


def _keywords(text: str, n: int = 30) -> list[str]:
    tokens = re.findall(r"[a-z][a-z0-9\-]{2,}", text.lower())
    freq: dict[str, int] = {}
    for t in tokens:
        if t not in STOPWORDS:
            freq[t] = freq.get(t, 0) + 1
    return sorted(freq, key=lambda k: -freq[k])[:n]


def _save_page_image(page: fitz.Page, path: Path) -> Path:
    mat = fitz.Matrix(1.5, 1.5)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    jpg = path.with_suffix(".jpg")
    img.save(jpg, "JPEG", quality=85, optimize=True)
    return jpg


def process_pdf(pdf_name: str) -> list[PageRecord]:
    pdf_path = FILES_DIR / f"{pdf_name}.pdf"
    if not pdf_path.exists():
        logger.warning("PDF not found: %s", pdf_path)
        return []

    out_dir = PAGES_DIR / pdf_name
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(pdf_path))
    logger.info("Processing %s (%d pages)", pdf_name, len(doc))

    records = []
    for i, page in enumerate(doc):
        saved = _save_page_image(page, out_dir / f"page_{i}")
        text = page.get_text("text").strip()
        records.append(PageRecord(
            pdf=pdf_name,
            page=i + 1,
            text=text,
            page_type=_classify(text),
            keywords=_keywords(text),
            image_path=str(saved.relative_to(BASE_DIR)).replace("\\", "/"),
        ))

    doc.close()
    logger.info("Done: %s (%d pages)", pdf_name, len(records))
    return records


def build_index(force: bool = False) -> list[PageRecord]:
    if not force and INDEX_PATH.exists():
        return load_index()

    DATA_DIR.mkdir(exist_ok=True)
    PAGES_DIR.mkdir(exist_ok=True)

    records: list[PageRecord] = []
    for name in PDF_NAMES:
        records.extend(process_pdf(name))

    INDEX_PATH.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": len(records),
        "pages": [asdict(r) for r in records],
    }, indent=2), encoding="utf-8")

    logger.info("Index saved: %d pages", len(records))
    return records


def load_index() -> list[PageRecord]:
    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return [PageRecord(**p) for p in data["pages"]]


def get_page_image_path(pdf_name: str, page_num: int) -> Path | None:
    for ext in (".jpg", ".png"):
        p = PAGES_DIR / pdf_name / f"page_{page_num - 1}{ext}"
        if p.exists():
            return p
    return None


def page_to_base64(pdf_name: str, page_num: int) -> tuple[str, str] | None:
    path = get_page_image_path(pdf_name, page_num)
    if path is None:
        return None

    raw = path.read_bytes()
    if path.suffix.lower() in (".jpg", ".jpeg"):
        return base64.b64encode(raw).decode(), "image/jpeg"

    buf = BytesIO()
    Image.open(path).convert("RGB").save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode(), "image/jpeg"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    records = build_index(force="--force" in sys.argv)
    print(f"\nDone — {len(records)} pages indexed")
