"""
Document loaders for the ingestion pipeline.

Provides two loaders:
  - load_pdf: extracts text from a local PDF file using pypdf
  - load_url: fetches and parses a web page using httpx + BeautifulSoup
"""
from __future__ import annotations

import logging

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def load_pdf(path: str) -> str:
    """
    Load and extract all text from a PDF file.

    Args:
        path: Absolute or relative path to the PDF file.

    Returns:
        Extracted text as a single string with pages separated by form-feed
        characters (\\f) for downstream chunking awareness.

    Raises:
        FileNotFoundError: If the file does not exist.
        RuntimeError: If pypdf cannot read the file.
    """
    from pypdf import PdfReader

    logger.info("Loading PDF: %s", path)
    try:
        reader = PdfReader(path)
    except Exception as exc:
        raise RuntimeError(f"Cannot open PDF at {path!r}: {exc}") from exc

    pages: list[str] = []
    for page_num, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
            pages.append(text)
        except Exception as exc:
            logger.warning("Failed to extract text from page %d: %s", page_num, exc)
            pages.append("")

    full_text = "\f".join(pages)
    logger.info(
        "Loaded PDF: %s — %d pages, %d characters",
        path,
        len(reader.pages),
        len(full_text),
    )
    return full_text


def load_url(url: str, timeout: float = 30.0) -> str:
    """
    Fetch a web page and extract its readable text content.

    Strips navigation, scripts, styles, and other non-content elements.
    Attempts to find the main article/content block; falls back to <body>.

    Args:
        url: HTTP/HTTPS URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        Cleaned text content of the page.

    Raises:
        httpx.HTTPError: On network or HTTP errors.
        RuntimeError: If no usable text content is found.
    """
    logger.info("Fetching URL: %s", url)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; KyronInvestBot/1.0; "
            "+https://kyroninvest.de/bot)"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en,de;q=0.9",
    }

    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove non-content tags.
    for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                     "noscript", "form", "button", "iframe", "figure"]):
        tag.decompose()

    # Try to find the main content block.
    content_element = (
        soup.find("article")
        or soup.find("main")
        or soup.find(id="content")
        or soup.find(class_="content")
        or soup.find("body")
    )

    if content_element is None:
        raise RuntimeError(f"No content found at URL: {url}")

    # Get text with reasonable separator.
    text = content_element.get_text(separator="\n", strip=True)

    # Collapse excessive whitespace / blank lines.
    lines = [line.strip() for line in text.splitlines()]
    cleaned_lines = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                cleaned_lines.append("")
            prev_blank = True
        else:
            cleaned_lines.append(line)
            prev_blank = False

    result = "\n".join(cleaned_lines).strip()

    logger.info("Fetched URL: %s — %d characters", url, len(result))

    if not result:
        raise RuntimeError(f"Empty content extracted from URL: {url}")

    return result
