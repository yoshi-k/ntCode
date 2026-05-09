from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

from utils.config import logger


_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class _DuckDuckGoHTMLParser(HTMLParser):
    """Small fallback parser for https://duckduckgo.com/html/ results.

    The Python DDGS client occasionally returns an empty result set or fails
    because DuckDuckGo changes its upstream behaviour.  The lightweight HTML
    endpoint is not ideal, but it gives us an independent fallback without
    adding BeautifulSoup as another dependency.
    """

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v or "" for k, v in attrs}
        classes = set(attr.get("class", "").split())

        if tag == "a" and "result__a" in classes:
            self._current = {"title": "", "snippet": "", "link": _normalise_ddg_url(attr.get("href", ""))}
            self._capture = "title"
            self._parts = []
        elif self._current is not None and tag in {"a", "div"} and "result__snippet" in classes:
            self._capture = "snippet"
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture == "title" and tag == "a" and self._current is not None:
            self._current["title"] = _clean_text(" ".join(self._parts))
            self._capture = None
            self._parts = []
        elif self._capture == "snippet" and tag in {"a", "div"} and self._current is not None:
            self._current["snippet"] = _clean_text(" ".join(self._parts))
            self._capture = None
            self._parts = []
            if self._current.get("title") or self._current.get("link"):
                self.results.append(self._current)
            self._current = None


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _normalise_ddg_url(url: str) -> str:
    """Convert DuckDuckGo redirect links to the real target where possible."""
    if not url:
        return ""

    parsed = urlparse(url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg")
        if uddg:
            return unquote(uddg[0])
    return url


def _row_to_result(row: dict[str, Any]) -> dict[str, str]:
    return {
        "title": str(row.get("title") or ""),
        "snippet": str(row.get("body") or row.get("snippet") or ""),
        "link": _normalise_ddg_url(str(row.get("href") or row.get("url") or "")),
    }


def _deduplicate(results: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for item in results:
        key = (item.get("link", ""), item.get("title", ""))
        if key in seen:
            continue
        if not item.get("title") and not item.get("link"):
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _load_ddgs_class():
    """Load the current DDGS client.

    The upstream project was renamed from ``duckduckgo_search`` to ``ddgs``.
    Supporting both names makes the tool work with old and new installs.
    """
    try:
        from ddgs import DDGS  # type: ignore

        return DDGS
    except Exception:
        from duckduckgo_search import DDGS  # type: ignore

        return DDGS


def _instantiate_ddgs(DDGS):
    try:
        return DDGS(timeout=10)
    except TypeError:
        return DDGS()


def _search_with_library(query: str, max_results: int) -> list[dict[str, str]]:
    DDGS = _load_ddgs_class()
    results: list[dict[str, str]] = []

    # Try multiple backends because the library has changed defaults over
    # time, and individual backends can intermittently return nothing.
    for backend in ("auto", "html", "lite"):
        try:
            with _instantiate_ddgs(DDGS) as ddgs:
                try:
                    rows = ddgs.text(
                        query,
                        region="wt-wt",
                        safesearch="moderate",
                        backend=backend,
                        max_results=max_results,
                    )
                except TypeError:
                    # Older versions do not expose all keyword arguments.
                    rows = ddgs.text(query, max_results=max_results)

                batch = [_row_to_result(r) for r in rows]
                results.extend(batch)
                if batch:
                    logger.debug("search_web_tool: DDGS backend '%s' returned %d results", backend, len(batch))
                    break
        except Exception as exc:  # noqa: BLE001 - tool should report, not crash
            logger.warning("search_web_tool: DDGS backend '%s' failed: %s", backend, exc)

    return _deduplicate(results, max_results)


def _search_with_html_fallback(query: str, max_results: int) -> list[dict[str, str]]:
    import httpx

    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    response = httpx.get(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        follow_redirects=True,
        timeout=15.0,
    )
    response.raise_for_status()

    parser = _DuckDuckGoHTMLParser()
    parser.feed(response.text)
    return _deduplicate(parser.results, max_results)


def search_web_tool(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """
    Searches the web using DuckDuckGo.

    :param query: The search query string.
    :param max_results: Maximum number of results to return.
    :return: A list of dictionaries containing 'title', 'snippet', and 'link'.
    """
    query = (query or "").strip()
    if not query:
        return [{"error": "Search failed: query must not be empty"}]

    try:
        max_results = max(1, min(int(max_results), 25))
    except (TypeError, ValueError):
        max_results = 5

    logger.info("Executing search_web_tool with query: '%s'", query)

    errors: list[str] = []

    try:
        results = _search_with_library(query, max_results)
        if results:
            return results
        errors.append("DDGS returned no results")
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_web_tool: DDGS search failed: %s", exc)
        errors.append(f"DDGS failed: {exc}")

    try:
        results = _search_with_html_fallback(query, max_results)
        if results:
            return results
        errors.append("DuckDuckGo HTML fallback returned no results")
    except Exception as exc:  # noqa: BLE001
        logger.error("search_web_tool: HTML fallback failed: %s", exc)
        errors.append(f"HTML fallback failed: {exc}")

    return [{"error": "Search failed: " + "; ".join(errors)}]
