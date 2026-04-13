from duckduckgo_search import DDGS
from utils.security import validate_file_access
from utils.config import logger


def search_web_tool(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """
    Searches the web using DuckDuckGo.

    :param query: The search query string.
    :param max_results: Maximum number of results to return.
    :return: A list of dictionaries containing 'title', 'snippet', and 'link'.
    """
    logger.info(f"Executing search_web_tool with query: '{query}'")
    
    results = []
    try:
        with DDGS() as ddgs:
            # ddgs.text returns a generator of dicts
            search_gen = ddgs.text(query, max_results=max_results)
            for r in search_gen:
                results.append({
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "link": r.get("href", "")
                })
    except Exception as e:
        logger.error(f"Error during DuckDuckGo search: {e}")
        return [{"error": f"Search failed: {str(e)}"}]

    return results
