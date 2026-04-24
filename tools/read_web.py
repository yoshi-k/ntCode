from urllib.parse import urlparse


def validate_url(url: str) -> bool:
    """Basic validation to ensure the URL has a valid scheme and netloc."""
    try:
        result = urlparse(url)
        return all([result.scheme in ["http", "https"], result.netloc])
    except Exception:
        return False

def read_web_tool(url: str) -> dict:
    """Fetches a webpage and extracts its main text content.
    :param url: The URL of the webpage to read.
    :return: A dictionary containing the extracted text or an error message.
    """
    # Lazy imports so the tool can be registered without these deps installed.
    import httpx
    import trafilatura

    if not validate_url(url):
        return {"error": f"Invalid URL: {url}", "success": False}

    try:
        response = httpx.get(url, follow_redirects=True, timeout=10.0)
        response.raise_for_status()
        
        downloaded = response.text
        extracted = trafilatura.extract(downloaded)
        
        if not extracted:
            return {"error": "Could not extract meaningful content from the page.", "success": False}
            
        return {"content": extracted, "success": True}
        
    except httpx.HTTPStatusError as e:
        return {"error": f"HTTP error: {e.response.status_code}", "success": False}
    except Exception as e:
        return {"error": f"Failed to read web page: {str(e)}", "success": False}
