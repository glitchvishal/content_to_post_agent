import httpx
import pytest

from agent.errors import FetchError
from agent.fetch import chunk_text, extract_article, fetch_url, normalize_text

HTML = """
<html><head><title>Fallback title</title><meta property="og:title" content="The Real Title"></head>
<body>
  <nav>Home | About</nav>
  <article>
    <h1>The Real Title</h1>
    <p>First paragraph of the article.</p>
    <script>trackUser()</script>
    <ul><li><p>A list item with a nested paragraph.</p></li></ul>
    <p>Second paragraph.</p>
  </article>
  <footer>Copyright</footer>
</body></html>
"""


def test_extract_article_keeps_content_and_drops_boilerplate():
    title, text = extract_article(HTML)
    assert title == "The Real Title"
    assert "First paragraph of the article." in text
    assert "Second paragraph." in text
    assert text.count("A list item with a nested paragraph.") == 1  # nested <p> not duplicated
    for noise in ("Home | About", "trackUser", "Copyright"):
        assert noise not in text


def test_normalize_text_keeps_paragraphs():
    assert normalize_text("a   b\r\n\r\n\r\n\nc\t d ") == "a b\n\nc d"


def test_chunks_respect_paragraph_boundaries():
    text = "\n\n".join(["Paragraph one is here."] * 3 + ["Another paragraph that is a bit longer."])
    chunks = chunk_text(text, max_chars=60)
    assert all(len(c) <= 60 for c in chunks)
    # No paragraph is cut in half: each chunk is made of whole paragraphs.
    for chunk in chunks:
        for part in chunk.split("\n\n"):
            assert part in ("Paragraph one is here.", "Another paragraph that is a bit longer.")


def test_long_paragraph_splits_at_sentences_then_words():
    sentences = " ".join(f"Sentence number {i} ends here." for i in range(20))
    chunks = chunk_text(sentences, max_chars=100)
    assert all(len(c) <= 100 for c in chunks)
    assert all(c.endswith(".") for c in chunks)  # split at sentence ends
    assert " ".join(chunks) == sentences  # nothing lost

    no_punctuation = "word " * 100
    assert all(len(c) <= 50 for c in chunk_text(no_punctuation, max_chars=50))


def _mock(handler):
    return httpx.MockTransport(handler)


def test_fetch_url_success_and_plain_text():
    html_transport = _mock(lambda r: httpx.Response(200, html=HTML))
    title, text = fetch_url("https://example.com/a", allow_private=True, transport=html_transport)
    assert title == "The Real Title" and "Second paragraph." in text

    text_transport = _mock(lambda r: httpx.Response(200, text="plain body", headers={"content-type": "text/plain"}))
    assert fetch_url("https://example.com/a.txt", allow_private=True, transport=text_transport) == ("", "plain body")


def test_fetch_url_retries_transient_errors_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] < 2 else httpx.Response(200, html=HTML)

    fetch_url("https://example.com", allow_private=True, max_attempts=3, transport=_mock(handler))
    assert calls["n"] == 2


def test_fetch_url_does_not_retry_404():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(404)

    with pytest.raises(FetchError, match="404"):
        fetch_url("https://example.com", allow_private=True, transport=_mock(handler))
    assert calls["n"] == 1


def test_fetch_url_rejects_bad_scheme_and_content_type():
    with pytest.raises(FetchError, match="http"):
        fetch_url("ftp://example.com/file")
    pdf = _mock(lambda r: httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"}))
    with pytest.raises(FetchError, match="Unsupported content type"):
        fetch_url("https://example.com/x.pdf", allow_private=True, transport=pdf)


def test_ssrf_guard_blocks_localhost():
    with pytest.raises(FetchError, match="private address"):
        fetch_url("http://127.0.0.1:9/", transport=_mock(lambda r: httpx.Response(200, html=HTML)))
