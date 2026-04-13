from __future__ import annotations

import logging
from typing import Any

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from preprocess import PDF_DISPLAY, load_index, page_to_base64

logger = logging.getLogger(__name__)

_index = None
_vectorizer: TfidfVectorizer | None = None
_matrix = None


def _ensure_index():
    global _index, _vectorizer, _matrix
    if _index is not None:
        return

    logger.info("Loading search index and fitting TF-IDF...")
    _index = load_index()
    corpus = [r.text or "" for r in _index]
    _vectorizer = TfidfVectorizer(max_df=0.85, min_df=1, ngram_range=(1, 2), sublinear_tf=True)
    _matrix = _vectorizer.fit_transform(corpus)
    logger.info("TF-IDF ready: %d pages, %d terms", len(_index), _matrix.shape[1])


def search_manual(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    _ensure_index()

    top_k = min(max(top_k, 1), 15)
    scores = cosine_similarity(_vectorizer.transform([query]), _matrix).flatten()

    # give diagram/mixed pages a slight boost so Claude gets prompted to fetch them
    for i, r in enumerate(_index):
        if r.page_type in ("diagram", "mixed"):
            scores[i] *= 1.15

    results = []
    for idx in np.argsort(scores)[::-1][:top_k]:
        if scores[idx] < 0.01:
            continue
        r = _index[idx]
        results.append({
            "pdf": r.pdf,
            "page": r.page,
            "page_type": r.page_type,
            "text_snippet": r.text[:150].strip() if r.text else "(diagram page)",
            "keywords": r.keywords[:8],
        })

    return results


def summarize_search_result(results: list[dict]) -> str:
    if not results:
        return "No relevant pages found."
    parts = []
    for r in results:
        tag = f" [{r['page_type']}]" if r["page_type"] != "text" else ""
        parts.append(f"{r['pdf']} p.{r['page']}{tag}")
    return "Found: " + ", ".join(parts)


def get_page_images(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for spec in pages[:2]:
        pdf_name = spec.get("pdf", "")
        page_num = int(spec.get("page", 0))
        got = page_to_base64(pdf_name, page_num)
        if got is None:
            logger.warning("Image not found: %s p%d", pdf_name, page_num)
            continue
        b64, mime = got
        results.append({
            "pdf": pdf_name,
            "pdf_display": PDF_DISPLAY.get(pdf_name, pdf_name),
            "page": page_num,
            "base64": b64,
            "media_type": mime,
        })
    return results


def format_images_for_claude(images: list[dict]) -> list[dict]:
    content = []
    for img in images:
        content.append({"type": "text", "text": f"[{img['pdf_display']}, Page {img['page']}]"})
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": img["media_type"], "data": img["base64"]},
        })
    return content


TOOL_SCHEMAS = [
    {
        "name": "search_manual",
        "description": (
            "Search the Vulcan OmniPro 220 manuals using TF-IDF. Returns matching pages "
            "with text snippets and page type. Use this when the pre-loaded results don't "
            "cover a different sub-topic you need."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Specific technical query, e.g. 'duty cycle 200A 240V' or 'TIG DCEN polarity'",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results (1–10, default 3)",
                    "default": 3,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_page_images",
        "description": (
            "Fetch actual page images from the manual for visual inspection. "
            "Use when text snippets reference a diagram, or when the question is specifically "
            "about wiring, polarity connectors, or a weld diagnosis chart."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "pdf": {
                                "type": "string",
                                "enum": ["owner-manual", "quick-start-guide", "selection-chart"],
                            },
                            "page": {"type": "integer"},
                        },
                        "required": ["pdf", "page"],
                    },
                    "minItems": 1,
                    "maxItems": 2,
                },
            },
            "required": ["pages"],
        },
    },
]
