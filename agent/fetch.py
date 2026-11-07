"""Fetch an article, clean it to plain text, and split it into chunks.

Chunking splits at natural boundaries in this order of preference:
paragraph  >  sentence  >  word.
Chunks are numbered so the planner can cite which chunk supports each key
point, and the judge can check posts against exactly that evidence.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from agent.errors import FetchError

USER_AGENT = "content-to-post-agent/0.1 (+https://github.com/glitchvishal/content-to-post-agent)"
MAX_BYTES = 3_000_000
_NOISE_TAGS = ["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe", "button"]
_BLOCK_TAGS = ["h1", "h2", "h3", "h4", "p", "li", "blockquote", "pre"]
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


class _RetryableStatus(Exception):
    """HTTP status worth retrying (429 / 5xx)."""


# Network problems and server-side errors are transient -> retry with backoff.
# 4xx errors, wrong content types etc. are not -> fail fast with a clear message.
_TRANSIENT = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, _RetryableStatus)


# --------------------------------------------------------------------------- fetching


def _guard_private_hosts(request: httpx.Request) -> None:
    """SSRF guard: refuse URLs that resolve to localhost or private networks.

    Runs on every request, including redirects. (DNS can change between this
    check and the connection; a production deployment should also restrict
    egress at the network level.)
    """
    host = request.url.host
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve host '{host}'.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise FetchError(f"Refusing to fetch '{host}': it resolves to a private address.")


def fetch_url(
    url: str,
    *,
    timeout_s: float = 15.0,
    max_attempts: int = 3,
    allow_private: bool = False,
    transport: httpx.BaseTransport | None = None,  # injectable for tests
) -> tuple[str, str]:
    """Download `url` and return (title, clean_text)."""
    if urlparse(url).scheme not in ("http", "https"):
        raise FetchError("Only http(s) URLs are supported.")

    hooks = {} if allow_private else {"request": [_guard_private_hosts]}
    client = httpx.Client(
        timeout=timeout_s,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9"},
        event_hooks=hooks,
        transport=transport,
    )

    def _get() -> httpx.Response:
        response = client.get(url)
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableStatus(f"HTTP {response.status_code}")
        if response.status_code >= 400:
            raise FetchError(f"The page returned HTTP {response.status_code}.")
        return response

    try:
        with client:
            for attempt in Retrying(
                stop=stop_after_attempt(max_attempts),
                wait=wait_exponential(multiplier=0.5, max=8),
                retry=retry_if_exception_type(_TRANSIENT),
                reraise=True,
            ):
                with attempt:
                    response = _get()
    except _TRANSIENT as exc:
        raise FetchError(f"Could not fetch the URL after {max_attempts} attempts: {exc}") from exc

    content_type = response.headers.get("content-type", "").lower()
    if len(response.content) > MAX_BYTES:
        raise FetchError("The page is too large (over 3 MB).")
    if "html" in content_type:
        return extract_article(response.text)
    if content_type.startswith("text/plain"):
        return "", normalize_text(response.text)
    raise FetchError(f"Unsupported content type '{content_type or 'unknown'}'. Paste the text instead.")


# --------------------------------------------------------------------------- cleaning


def extract_article(html: str) -> tuple[str, str]:
    """Pull the readable article text out of an HTML page.

    Heuristic, dependency-light approach: drop obvious boilerplate tags, prefer
    <article> or <main>, and keep text from headings, paragraphs and list items.
    """
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    elif soup.title and soup.title.string:
        title = soup.title.string.strip()
    elif soup.h1:
        title = soup.h1.get_text(" ", strip=True)

    for tag in soup(_NOISE_TAGS):
        tag.decompose()

    root = soup.find("article") or soup.find("main") or soup.body or soup
    blocks: list[str] = []
    for element in root.find_all(_BLOCK_TAGS):
        # Skip blocks nested in another block (e.g. <p> inside <li>) to avoid duplicates.
        if element.find_parent(["p", "li", "blockquote"]):
            continue
        text = re.sub(r"\s+", " ", element.get_text(" ", strip=True))
        if len(text) > 1 and (not blocks or blocks[-1] != text):
            blocks.append(text)

    if not blocks:  # pages without semantic tags
        return title, normalize_text(root.get_text("\n"))
    return title, "\n\n".join(blocks)


def normalize_text(text: str) -> str:
    """Normalise whitespace while keeping paragraph breaks (blank lines)."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# --------------------------------------------------------------------------- chunking


def split_paragraphs(text: str) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    # Text with single line breaks only: treat each line as a paragraph.
    if len(paragraphs) == 1 and "\n" in paragraphs[0]:
        paragraphs = [line.strip() for line in paragraphs[0].split("\n") if line.strip()]
    return paragraphs


def _pack(pieces: list[str], max_chars: int, sep: str) -> list[str]:
    """Greedily join pieces with `sep` into groups no longer than max_chars."""
    groups: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current}{sep}{piece}" if current else piece
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                groups.append(current)
            current = piece
    if current:
        groups.append(current)
    return groups


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """Split one oversized paragraph at sentence ends, falling back to word boundaries."""
    pieces: list[str] = []
    for sentence in _SENTENCE_END.split(paragraph):
        if len(sentence) <= max_chars:
            pieces.append(sentence)
        else:  # a single huge "sentence" (e.g. no punctuation): wrap at words
            pieces.extend(_pack(sentence.split(), max_chars, " "))
    return _pack(pieces, max_chars, " ")


def chunk_text(text: str, max_chars: int = 1500) -> list[str]:
    """Split text into chunks of at most `max_chars`, at paragraph > sentence > word boundaries."""
    pieces: list[str] = []
    for paragraph in split_paragraphs(text):
        if len(paragraph) <= max_chars:
            pieces.append(paragraph)
        else:
            pieces.extend(_split_long_paragraph(paragraph, max_chars))
    return _pack(pieces, max_chars, "\n\n")
