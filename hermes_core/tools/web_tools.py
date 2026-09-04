import httpx
import json
import urllib.parse
from hermes_core.tools.registry import registry

@registry.register(
    name="web_search",
    description="Search the web for real-time information, news, documentation, or facts.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query keywords"}
        },
        "required": ["query"]
    },
    category="web"
)
async def web_search(query: str) -> str:
    """Execute fast web search via DuckDuckGo Instant Answer / HTML API."""
    try:
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json&no_html=1&skip_disambig=1"
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            if resp.status_code == 200:
                data = resp.json()
                abstract = data.get("AbstractText", "")
                related = [r.get("Text", "") for r in data.get("RelatedTopics", []) if "Text" in r][:4]
                if abstract or related:
                    return json.dumps({"abstract": abstract, "related": related}, ensure_ascii=False)
            
            # Fallback to HTML scrape
            html_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
            html_resp = await client.post(html_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            if html_resp.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html_resp.text, "html.parser")
                results = []
                for r in soup.find_all("a", class_="result__snippet")[:5]:
                    results.append(r.get_text(strip=True))
                if results:
                    return json.dumps({"results": results}, ensure_ascii=False)
        return json.dumps({"result": f"No direct search results found for '{query}'."})
    except Exception as e:
        return json.dumps({"error": f"Search failed: {str(e)}"})

@registry.register(
    name="fetch_webpage",
    description="Fetch and extract readable text content from a given web URL.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The web URL to fetch"}
        },
        "required": ["url"]
    },
    category="web"
)
async def fetch_webpage(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            if resp.status_code == 200:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                    tag.decompose()
                text = " ".join(soup.get_text(separator=" ").split())
                return text[:4000]
            return f"Failed to fetch {url}: HTTP {resp.status_code}"
    except Exception as e:
        return f"Error fetching webpage {url}: {str(e)}"
