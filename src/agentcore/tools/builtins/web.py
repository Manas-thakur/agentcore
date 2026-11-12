"""Network tools: ``http_get`` and a DuckDuckGo HTML ``web_search``.

Both need internet access; they are not used by the offline examples or tests (tests
inject an ``httpx.MockTransport``).
"""

from __future__ import annotations

import html
import re
import urllib.parse
from html.parser import HTMLParser
from typing import Any

import httpx

from agentcore.tools.decorator import Tool, tool
from agentcore.tools.errors import ToolExecutionError, ToolTransientError

USER_AGENT = "agentcore/0.1 (+https://github.com/Manas-thakur/agentcore)"


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self.SKIP:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if not self._skip:
            self.parts.append(data)


def html_to_text(markup: str) -> tuple[str, str]:
    """Extract ``(title, text)`` from HTML using only the standard library."""
    parser = _TextExtractor()
    parser.feed(markup)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return parser.title.strip(), text.strip()


def make_http_get(client: httpx.Client | None = None, max_chars: int = 20_000) -> Tool:
    @tool(category="web", timeout=30, retries=1)
    def http_get(url: str) -> str:
        """Fetch a URL over HTTP(S) and return its readable text content.

        Args:
            url: Absolute http(s) URL to fetch.
        """
        if not url.startswith(("http://", "https://")):
            raise ToolExecutionError("only http(s) URLs are allowed")
        c = client or httpx.Client(timeout=20, follow_redirects=True)
        try:
            resp = c.get(url, headers={"User-Agent": USER_AGENT})
        except httpx.TransportError as exc:
            raise ToolTransientError(str(exc)) from exc
        if resp.status_code >= 500:
            raise ToolTransientError(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise ToolExecutionError(f"HTTP {resp.status_code} for {url}")
        ctype = resp.headers.get("content-type", "")
        body = resp.text
        if "html" in ctype or body.lstrip().startswith("<"):
            title, body = html_to_text(body)
            body = f"# {title}\n\n{body}" if title else body
        return body[:max_chars]

    return http_get


def parse_ddg_html(markup: str, max_results: int = 5) -> list[dict[str, str]]:
    """Parse results from ``html.duckduckgo.com/html`` markup."""
    results = []
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
        r'class="result__snippet"[^>]*>(.*?)</(?:a|div)>',
        re.S,
    )
    for href, title, snippet in pattern.findall(markup):
        url = href
        if "uddg=" in href:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(html.unescape(href)).query)
            url = qs.get("uddg", [href])[0]
        clean = lambda s: html.unescape(re.sub(r"<[^>]+>", "", s)).strip()  # noqa: E731
        results.append({"title": clean(title), "url": url, "snippet": clean(snippet)})
        if len(results) >= max_results:
            break
    return results


def make_web_search(client: httpx.Client | None = None) -> Tool:
    @tool(category="web", timeout=30, retries=1)
    def web_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
        """Search the web (DuckDuckGo) and return a list of {title, url, snippet}.

        Args:
            query: Search query.
            max_results: Maximum number of results to return (1-10).
        """
        c = client or httpx.Client(timeout=20, follow_redirects=True)
        try:
            resp = c.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query},
                headers={"User-Agent": USER_AGENT},
            )
        except httpx.TransportError as exc:
            raise ToolTransientError(str(exc)) from exc
        if resp.status_code != 200:
            raise ToolTransientError(f"search failed: HTTP {resp.status_code}")
        return parse_ddg_html(resp.text, max(1, min(max_results, 10)))

    return web_search


http_get = make_http_get()
web_search = make_web_search()
