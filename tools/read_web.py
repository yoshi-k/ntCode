from __future__ import annotations

from html.parser import HTMLParser
from urllib.parse import urlparse

from utils.config import logger


_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_MAX_CONTENT_CHARS = 80_000


def validate_url(url: str) -> bool:
    """Basic validation to ensure the URL has a valid scheme and netloc."""
    try:
        result = urlparse(url)
        return all([result.scheme in ["http", "https"], result.netloc])
    except Exception:
        return False


class _ReadableTextParser(HTMLParser):
    """Very small plain-text fallback extractor for HTML pages."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas"}
    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            text = data.strip()
            if text:
                self._parts.append(text)
                self._parts.append(" ")

    def text(self) -> str:
        lines = []
        for line in "".join(self._parts).splitlines():
            cleaned = " ".join(line.split())
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines)


def _fallback_extract_text(html: str) -> str:
    parser = _ReadableTextParser()
    parser.feed(html)
    return parser.text()


def _extract_text(downloaded: str, url: str) -> tuple[str, str]:
    import trafilatura

    extracted = trafilatura.extract(
        downloaded,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_recall=True,
    )
    if extracted:
        return extracted, "trafilatura"

    fallback = _fallback_extract_text(downloaded)
    if fallback:
        return fallback, "html_fallback"

    return "", "none"


def read_web_tool(url: str) -> dict:
    """Fetches a webpage and extracts its main text content.
    :param url: The URL of the webpage to read.
    :return: A dictionary containing the extracted text or an error message.
    """
    # Lazy imports so the tool can be registered without these deps installed.
    import httpx

    url = (url or "").strip()
    if not validate_url(url):
        return {"error": f"Invalid URL: {url}", "success": False}

    try:
        response = httpx.get(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
            timeout=20.0,
        )
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if not any(kind in content_type.lower() for kind in ("text/", "html", "xml", "json")):
            return {
                "error": f"Unsupported content type: {content_type or 'unknown'}",
                "success": False,
                "url": str(response.url),
                "status_code": response.status_code,
            }

        downloaded = response.text
        extracted, extractor = _extract_text(downloaded, str(response.url))

        if not extracted:
            return {
                "error": "Could not extract meaningful content from the page.",
                "success": False,
                "url": str(response.url),
                "status_code": response.status_code,
            }

        truncated = len(extracted) > _MAX_CONTENT_CHARS
        if truncated:
            extracted = extracted[:_MAX_CONTENT_CHARS].rstrip() + "\n\n[Content truncated]"

        return {
            "content": extracted,
            "success": True,
            "url": str(response.url),
            "status_code": response.status_code,
            "extractor": extractor,
            "truncated": truncated,
        }

    except httpx.HTTPStatusError as e:
        logger.warning("read_web_tool: HTTP error reading %s: %s", url, e)
        return {
            "error": f"HTTP error: {e.response.status_code}",
            "success": False,
            "url": str(e.response.url),
            "status_code": e.response.status_code,
        }
    except httpx.RequestError as e:
        logger.warning("read_web_tool: request failed for %s: %s", url, e)
        return {"error": f"Request failed: {str(e)}", "success": False}
    except Exception as e:
        logger.error("read_web_tool: failed to read %s: %s", url, e)
        return {"error": f"Failed to read web page: {str(e)}", "success": False}
