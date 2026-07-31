"""Read-only live catalog helpers for Fragment gifts."""

import re
from typing import Optional

import aiohttp

from .exceptions import FragmentCatalogError

FRAGMENT_BASE = "https://fragment.com"

_COLLECTION_BLOCK_RE = re.compile(
    r'js-choose-collection-item" data-keywords="[^"]*" data-value="([a-z0-9]+)">(.*?)</a>', re.DOTALL
)
_COLLECTION_NAME_RE = re.compile(r'tm-main-filters-name">([^<]+)<')
_ITEM_BLOCK_RE = re.compile(
    r'<a href="(/gift/([a-z0-9-]+)-(\d+))[^"]*"[^>]*class="tm-grid-item">(.*?)</a>', re.DOTALL
)
_IMG_RE = re.compile(r'<img src="([^"]+)"')
_PRICE_RE = re.compile(r'tm-grid-item-value[^>]*>([\d,]+)<')
_STATUS_RE = re.compile(r'tm-grid-item-status ([a-z-]+)">([^<]+)<')
_NAME_RE = re.compile(r'class="item-name">([^<]+)<')


def _absolute_url(value: Optional[str]) -> Optional[str]:
    if value and value.startswith("/"):
        return f"{FRAGMENT_BASE}{value}"
    return value or None


def _parse_items(html: str, collection: str, limit: int) -> list[dict]:
    items = []
    for match in _ITEM_BLOCK_RE.finditer(html):
        if len(items) >= limit:
            break
        _href, slug, number, block = match.groups()
        status = _STATUS_RE.search(block)
        price = _PRICE_RE.search(block)
        if not status or "avail" not in status.group(1) or not price:
            continue
        image = _IMG_RE.search(block)
        name = _NAME_RE.search(block)
        item_slug = f"{slug}-{number}"
        items.append({
            "slug": item_slug,
            "collection": collection,
            "number": int(number),
            "name": name.group(1).strip() if name else slug,
            "price_ton": float(price.group(1).replace(",", "")),
            "image_url": _absolute_url(image.group(1)) if image else None,
            "url": f"{FRAGMENT_BASE}/gift/{item_slug}",
            "status": "for_sale",
        })
    return items


class FragmentCatalog:
    """Live read-only catalog access. No wallet or mnemonic is required."""

    def __init__(self, fragment_cookies: Optional[str] = None):
        self.fragment_cookies = fragment_cookies

    def _headers(self) -> dict:
        headers = {"User-Agent": "fragment-ton-api-fraga/0.1"}
        if self.fragment_cookies:
            headers["Cookie"] = self.fragment_cookies
        return headers

    async def list_collections(self) -> list[dict]:
        async with aiohttp.ClientSession(headers=self._headers()) as session:
            async with session.get(f"{FRAGMENT_BASE}/gifts") as response:
                response.raise_for_status()
                html = await response.text()

        result = []
        seen = set()
        for match in _COLLECTION_BLOCK_RE.finditer(html):
            slug, block = match.groups()
            if slug in seen:
                continue
            name = _COLLECTION_NAME_RE.search(block)
            if name:
                seen.add(slug)
                result.append({
                    "slug": slug,
                    "name": name.group(1).strip(),
                    "url": f"{FRAGMENT_BASE}/gifts/{slug}",
                })
        return result

    async def list_gifts(self, collection_slug: str, limit: int = 60, sort: str = "price") -> list[dict]:
        """Return currently available fixed-price gifts from one collection."""
        if not 1 <= limit <= 200:
            raise FragmentCatalogError("limit must be between 1 and 200")
        if sort not in {"price", "recent"}:
            raise FragmentCatalogError("sort must be 'price' or 'recent'")
        url = f"{FRAGMENT_BASE}/gifts/{collection_slug}?sort={sort}&filter=sale"
        async with aiohttp.ClientSession(headers=self._headers()) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                html = await response.text()
        return _parse_items(html, collection_slug, limit)
