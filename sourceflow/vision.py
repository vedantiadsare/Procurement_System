"""Reading documents that contain no text - scans, and PDFs exported as images.

A signed SFO is very often a scan: someone prints the form, signs it, scans it
back. Four pages, zero characters, one flat picture per page. Every text
extractor returns nothing, correctly, because there is nothing to extract.

This renders each page and asks a vision model what it says. That is a
different kind of answer from reading a text layer: the characters are being
inferred from pixels rather than read off the page, so everything that comes
back through here is marked lower confidence and shown to a reviewer as
"please check". The model is run locally through the same Ollama endpoint as
the rest of the app - no cloud, no key, works offline.

Never raises. Returns ("", reason) when there is no vision model configured or
the render fails, so a caller can carry on with whatever it did have.
"""

import base64
import io
import logging

import httpx

from config import LLM_MODE, OLLAMA_BASE_URL, VISION_MODEL

logger = logging.getLogger("sourceflow.vision")

# A page at 150dpi is legible to a vision model and still small enough to send
# without the request becoming the slow part. Higher resolutions cost time for
# very little accuracy on a printed form.
RENDER_DPI = 150

# Most procurement documents say what they need to in their first pages;
# signature and footnote pages rarely carry fields. Bounded so one long scan
# can't tie up the model for minutes.
MAX_PAGES = 4

_PROMPT = (
    "This is a scanned page from a procurement document. Transcribe everything "
    "you can read, preserving the structure: keep each label with its value on "
    "the same line (for example 'Department: IT Infrastructure'), and keep table "
    "rows on one line with columns separated by | . Do not summarise, do not "
    "explain, do not add anything that is not printed on the page. If a field is "
    "blank, leave it blank."
)


def available() -> bool:
    return LLM_MODE == "ollama" and bool(VISION_MODEL)


def render_pdf_pages(pdf_bytes, max_pages=MAX_PAGES) -> list:
    """PDF pages as PNG bytes. Uses pdfplumber's renderer, which is already a
    dependency - no poppler or ImageMagick to install."""
    import pdfplumber
    images = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages[:max_pages]:
                buffer = io.BytesIO()
                page.to_image(resolution=RENDER_DPI).save(buffer, format="PNG")
                images.append(buffer.getvalue())
    except Exception as exc:
        logger.warning("Could not render PDF for vision reading: %s", exc)
    return images


def read_image(png_bytes, prompt=_PROMPT, timeout=240.0):
    """One page through the vision model. Returns (text, error)."""
    if not available():
        return "", "No vision model configured (SOURCEFLOW_VISION_MODEL is not set)."

    payload = {
        "model": VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": "data:image/png;base64," + base64.b64encode(png_bytes).decode()}},
            ],
        }],
        "temperature": 0,
    }
    try:
        response = httpx.post(f"{OLLAMA_BASE_URL}/chat/completions", json=payload, timeout=timeout)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return (content or "").strip(), None
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.json().get("error", {}).get("message", "")
        except Exception:
            detail = exc.response.text[:200]
        return "", f"Vision model returned {exc.response.status_code}: {detail}"
    except Exception as exc:
        return "", f"Vision model unavailable: {exc}"


def read_pdf(pdf_bytes, max_pages=MAX_PAGES) -> tuple:
    """Whole document. Returns (text, error). Pages that fail are skipped with
    a note rather than losing the pages that worked."""
    if not available():
        return "", "No vision model configured."

    images = render_pdf_pages(pdf_bytes, max_pages)
    if not images:
        return "", "Could not render any page of this PDF."

    parts, failures = [], []
    for index, png in enumerate(images, start=1):
        text, error = read_image(png)
        if text:
            parts.append(f"--- page {index} ---\n{text}")
        elif error:
            failures.append(f"page {index}: {error}")

    if not parts:
        return "", "; ".join(failures) or "Nothing could be read from this scan."
    return "\n\n".join(parts), ("; ".join(failures) if failures else None)
