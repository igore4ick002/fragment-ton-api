"""Tests for the network wrapper in FragmentCatalog.list_collections/list_gifts:
headers/cookies sent, raise_for_status behaviour, and the timeout passed to
aiohttp.ClientSession. _parse_items itself is covered in test_catalog.py."""

import logging

import pytest

import fragment_api.catalog as catalog_module
from fragment_api.catalog import FragmentCatalog
from fragment_api.exceptions import FragmentCatalogError

COLLECTIONS_HTML = """
<a class="js-choose-collection-item" data-keywords="lolpop" data-value="lolpop">
  <div class="tm-main-filters-name">Lol Pop</div>
</a>
"""

GIFTS_HTML = """
<a href="/gift/lol-pop-12345" class="tm-grid-item">
  <picture><img src="/file/preview.png"></picture>
  <div class="item-name">Lol Pop #12345</div>
  <div class="tm-grid-item-status avail">For sale</div>
  <div class="tm-grid-item-value">1,234</div>
</a>
"""


class FakeResponse:
    def __init__(self, *, text, status=200, raise_exc=None):
        self._text = text
        self.status = status
        self._raise_exc = raise_exc

    def raise_for_status(self):
        if self._raise_exc:
            raise self._raise_exc

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Fake aiohttp.ClientSession recording constructor kwargs and .get() calls."""

    last_instance = None

    def __init__(self, *, headers=None, timeout=None, **kwargs):
        self.headers = headers
        self.timeout = timeout
        self.get_calls = []
        FakeSession.last_instance = self

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return FakeSession.response_for(url)

    @staticmethod
    def response_for(url):
        raise NotImplementedError

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _install_fake_session(monkeypatch, response):
    def factory(*, headers=None, timeout=None, **kwargs):
        session = FakeSession(headers=headers, timeout=timeout)
        session.get = lambda url, **kw: (session.get_calls.append((url, kw)), response)[1]
        return session

    monkeypatch.setattr(catalog_module.aiohttp, "ClientSession", factory)
    return factory


@pytest.mark.asyncio
async def test_list_collections_sends_cookie_header_and_timeout(monkeypatch):
    response = FakeResponse(text=COLLECTIONS_HTML)
    _install_fake_session(monkeypatch, response)

    catalog = FragmentCatalog(fragment_cookies="stel_ssid=abc; stel_token=def")
    result = await catalog.list_collections()

    assert result == [{"slug": "lolpop", "name": "Lol Pop", "url": "https://fragment.com/gifts/lolpop"}]
    session = FakeSession.last_instance
    assert session.headers["Cookie"] == "stel_ssid=abc; stel_token=def"
    assert session.timeout is catalog_module.REQUEST_TIMEOUT
    assert session.get_calls[0][0] == "https://fragment.com/gifts"


@pytest.mark.asyncio
async def test_list_collections_without_cookies_omits_cookie_header(monkeypatch):
    response = FakeResponse(text=COLLECTIONS_HTML)
    _install_fake_session(monkeypatch, response)

    catalog = FragmentCatalog()
    await catalog.list_collections()

    assert "Cookie" not in FakeSession.last_instance.headers


@pytest.mark.asyncio
async def test_list_collections_propagates_http_errors(monkeypatch):
    response = FakeResponse(text="", raise_exc=RuntimeError("HTTP 500"))
    _install_fake_session(monkeypatch, response)

    catalog = FragmentCatalog()
    with pytest.raises(RuntimeError):
        await catalog.list_collections()


@pytest.mark.asyncio
async def test_list_gifts_builds_expected_url_and_parses_items(monkeypatch):
    response = FakeResponse(text=GIFTS_HTML)
    _install_fake_session(monkeypatch, response)

    catalog = FragmentCatalog()
    items = await catalog.list_gifts("lol-pop", limit=10, sort="recent")

    session = FakeSession.last_instance
    assert session.get_calls[0][0] == "https://fragment.com/gifts/lol-pop?sort=recent&filter=sale"
    assert len(items) == 1
    assert items[0]["slug"] == "lol-pop-12345"


@pytest.mark.asyncio
async def test_list_gifts_rejects_invalid_limit():
    catalog = FragmentCatalog()
    with pytest.raises(FragmentCatalogError):
        await catalog.list_gifts("lol-pop", limit=0)
    with pytest.raises(FragmentCatalogError):
        await catalog.list_gifts("lol-pop", limit=201)


@pytest.mark.asyncio
async def test_list_gifts_rejects_invalid_sort():
    catalog = FragmentCatalog()
    with pytest.raises(FragmentCatalogError):
        await catalog.list_gifts("lol-pop", sort="cheapest")


@pytest.mark.asyncio
async def test_list_collections_dedupes_repeated_slug(monkeypatch):
    html = COLLECTIONS_HTML + COLLECTIONS_HTML  # same slug twice
    _install_fake_session(monkeypatch, FakeResponse(text=html))

    catalog = FragmentCatalog()
    result = await catalog.list_collections()

    assert len(result) == 1


@pytest.mark.asyncio
async def test_list_collections_warns_when_nothing_parsed(monkeypatch, caplog):
    _install_fake_session(monkeypatch, FakeResponse(text="<html>no collections here</html>"))

    catalog = FragmentCatalog()
    with caplog.at_level(logging.WARNING):
        result = await catalog.list_collections()

    assert result == []
    assert any("parsed 0 collections" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_list_gifts_warns_when_nothing_parsed(monkeypatch, caplog):
    _install_fake_session(monkeypatch, FakeResponse(text="<html>no gifts here</html>"))

    catalog = FragmentCatalog()
    with caplog.at_level(logging.WARNING):
        items = await catalog.list_gifts("lol-pop")

    assert items == []
    assert any("parsed 0 items" in rec.message for rec in caplog.records)
