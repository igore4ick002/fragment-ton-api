"""Read-only live catalog helpers for Fragment gifts."""

import logging
import re
from typing import Optional

import aiohttp

from .emoji import get_gift_emoji
from .exceptions import FragmentCatalogError
from .types import AuctionInfo, CollectionItem, GiftItem, NumberItem, UsernameItem

logger = logging.getLogger(__name__)

FRAGMENT_BASE = "https://fragment.com"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

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

# ─── Numbers & Usernames: table-based layout (tm-row-selectable) ─────────────
# Fragment uses a table structure for numbers/usernames, NOT tm-grid-item.
_ROW_RE = re.compile(r'<tr\b[^>]*\btm-row-selectable\b[^>]*>(.*?)</tr>', re.DOTALL)
_ROW_NUM_HREF_RE = re.compile(r'href="/number/([^"?#\s]+)"')
_ROW_USR_HREF_RE = re.compile(r'href="/username/([^"?#\s]+)"')
# Display value (number "+888..." or username "@board") — class with no extra icon classes
_ROW_DISPLAY_RE = re.compile(r'class="table-cell-value tm-value"[^>]*>\s*([^<]+?)\s*</div>')
# Price cell has extra icon-ton classes
_ROW_PRICE_RE = re.compile(r'class="[^"]*table-cell-value[^"]*icon-ton[^"]*"[^>]*>\s*([\d,]+)\s*</div>')
# ISO 8601 datetime on <time> tags (auction end)
_ROW_DATETIME_RE = re.compile(r'<time\s+datetime="([^"]+)"')
# "For sale" marker vs auction
_ROW_AVAIL_RE = re.compile(r'tm-status-avail')
# ajInit JSON embedded in Fragment pages - contains auction details
_AJ_INIT_RE = re.compile(r'ajInit\s*\(\s*(\{.*?\})\s*\)', re.DOTALL)


def _iso_to_ts(dt_str: str) -> Optional[int]:
    """Convert ISO 8601 datetime string to unix timestamp."""
    try:
        from datetime import datetime, timezone
        s = dt_str.strip().replace('Z', '+00:00')
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            dt = datetime.strptime(s[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def _absolute_url(value: Optional[str]) -> Optional[str]:
    if value and value.startswith("/"):
        return f"{FRAGMENT_BASE}{value}"
    return value or None


NFT_CDN = "https://nft.fragment.com"


def gift_image_url(slug: str) -> str:
    """Returns the CDN image URL for a gift by its slug (e.g. 'artisan-brick-4700')."""
    return f"{NFT_CDN}/gift/{slug}.webp"


def _parse_items(html: str, collection: str, limit: int) -> list[GiftItem]:
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
        item_slug = f"{slug}-{number}"
        name = _NAME_RE.search(block)
        # Use parsed image URL if available, fall back to CDN pattern
        img_url = _absolute_url(image.group(1)) if image else gift_image_url(item_slug)
        items.append({
            "slug": item_slug,
            "collection": collection,
            "number": int(number),
            "name": name.group(1).strip() if name else slug,
            "price_ton": float(price.group(1).replace(",", "")),
            "image_url": img_url,
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

    async def list_collections(self) -> list[CollectionItem]:
        async with aiohttp.ClientSession(headers=self._headers(), timeout=REQUEST_TIMEOUT) as session:
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
                    "emoji": get_gift_emoji(slug),
                })
        if not result:
            logger.warning(
                "list_collections: parsed 0 collections from %d bytes of HTML — "
                "fragment.com markup may have changed (js-choose-collection-item / tm-main-filters-name)",
                len(html),
            )
        return result

    def _parse_rows(
        self,
        html: str,
        href_re: re.Pattern,
        item_type: str,
        limit: int,
        seen: set,
    ) -> list[dict]:
        """Parse tm-row-selectable table rows into a list of raw item dicts."""
        items: list[dict] = []
        for row_m in _ROW_RE.finditer(html):
            if len(items) >= limit:
                break
            block = row_m.group(1)
            href_m = href_re.search(block)
            if not href_m:
                continue
            slug = href_m.group(1)
            if slug in seen:
                continue
            seen.add(slug)
            price_m = _ROW_PRICE_RE.search(block)
            if not price_m:
                continue
            display_m = _ROW_DISPLAY_RE.search(block)
            dt_m = _ROW_DATETIME_RE.search(block)
            price = float(price_m.group(1).replace(",", ""))
            # tm-status-avail = fixed-price sale; its absence = auction
            is_for_sale = bool(_ROW_AVAIL_RE.search(block))
            is_auction = not is_for_sale
            # auction_end only makes sense for auction items (sale items have listing expiry, not auction end)
            auction_end = (_iso_to_ts(dt_m.group(1)) if dt_m else None) if is_auction else None
            display = (display_m.group(1).strip() if display_m else slug)
            if item_type == "username":
                display = display.lstrip("@")
            items.append({
                "slug": slug,
                "display": display,
                "price_ton": price,
                "min_bid_ton": price if is_auction else round(price * 1.05, 2),
                "auction_end": auction_end,
                "is_auction": is_auction,
                "status": "on_auction" if is_auction else "for_sale",
            })
        return items

    async def _fetch_html(self, url: str) -> str:
        async with aiohttp.ClientSession(headers=self._headers(), timeout=REQUEST_TIMEOUT) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                return await response.text()

    async def list_numbers(
        self,
        limit: int = 50,
        sort: str = "price",
        filter: str = "all",
    ) -> list[NumberItem]:
        """List anonymous phone numbers available on Fragment.

        filter: ``"all"`` (default) fetches both auction and fixed-price items;
                ``"auction"`` returns only items currently on auction;
                ``"sale"`` returns only fixed-price items.
        sort:   ``"price"`` (cheapest first) or ``"recent"`` (newest first).
        """
        if not 1 <= limit <= 500:
            raise FragmentCatalogError("limit must be between 1 and 500")
        sort_param = "price" if sort in ("price", "price_asc") else "recent"
        filters = ["auction", "sale"] if filter == "all" else [filter]

        seen: set[str] = set()
        raw: list[dict] = []
        for f in filters:
            url = f"{FRAGMENT_BASE}/numbers?sort={sort_param}&filter={f}"
            html = await self._fetch_html(url)
            rows = self._parse_rows(html, _ROW_NUM_HREF_RE, "number", limit * 2, seen)
            # Filter by actual auction status detected from HTML (timer presence)
            if f == "sale":
                rows = [r for r in rows if not r["is_auction"]]
            elif f == "auction":
                rows = [r for r in rows if r["is_auction"]]
            raw.extend(rows)

        # Sort combined list by price then slice
        if sort in ("price", "price_asc"):
            raw.sort(key=lambda x: x["price_ton"])
        raw = raw[:limit]

        items: list[NumberItem] = []
        for r in raw:
            items.append({
                "slug": r["slug"],
                "number": r["display"],
                "price_ton": r["price_ton"],
                "min_bid_ton": r["min_bid_ton"],
                "auction_end": r["auction_end"],
                "is_auction": r["is_auction"],
                "status": r["status"],
                "url": f"{FRAGMENT_BASE}/number/{r['slug']}",
            })

        if not items:
            logger.warning(
                "list_numbers: parsed 0 items (filter=%r, sort=%r) — fragment.com markup may have changed",
                filter, sort,
            )
        return items

    async def list_usernames(
        self,
        limit: int = 50,
        sort: str = "price",
        filter: str = "all",
    ) -> list[UsernameItem]:
        """List Telegram usernames available on Fragment.

        filter: ``"all"`` (default) fetches both auction and fixed-price items;
                ``"auction"`` returns only items on auction;
                ``"sale"`` returns only fixed-price items.
        sort:   ``"price"`` or ``"recent"``.
        """
        if not 1 <= limit <= 500:
            raise FragmentCatalogError("limit must be between 1 and 500")
        sort_param = "price" if sort in ("price", "price_asc") else "recent"
        filters = ["auction", "sale"] if filter == "all" else [filter]

        seen: set[str] = set()
        raw: list[dict] = []
        for f in filters:
            url = f"{FRAGMENT_BASE}/usernames?sort={sort_param}&filter={f}"
            html = await self._fetch_html(url)
            rows = self._parse_rows(html, _ROW_USR_HREF_RE, "username", limit * 2, seen)
            if f == "sale":
                rows = [r for r in rows if not r["is_auction"]]
            elif f == "auction":
                rows = [r for r in rows if r["is_auction"]]
            raw.extend(rows)

        if sort in ("price", "price_asc"):
            raw.sort(key=lambda x: x["price_ton"])
        raw = raw[:limit]

        items: list[UsernameItem] = []
        for r in raw:
            items.append({
                "slug": r["slug"],
                "username": r["display"],
                "price_ton": r["price_ton"],
                "min_bid_ton": r["min_bid_ton"],
                "auction_end": r["auction_end"],
                "is_auction": r["is_auction"],
                "status": r["status"],
                "url": f"{FRAGMENT_BASE}/username/{r['slug']}",
            })

        if not items:
            logger.warning(
                "list_usernames: parsed 0 items (filter=%r, sort=%r) — fragment.com markup may have changed",
                filter, sort,
            )
        return items

    async def get_auction_info(self, slug: str, item_type: str) -> AuctionInfo:
        """Fetch live auction details for a specific item by parsing its Fragment page.

        item_type: "gift" | "number" | "username"
        Returns AuctionInfo dict; current_bid / min_next_bid may be 0.0 if parsing fails.
        """
        import json as _json

        path = {"gift": "gift", "number": "number", "username": "username"}.get(item_type, item_type)
        url = f"{FRAGMENT_BASE}/{path}/{slug}"
        async with aiohttp.ClientSession(headers=self._headers(), timeout=REQUEST_TIMEOUT) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                html = await response.text()

        # Try ajInit JSON first (most reliable source of auction data)
        aj_data: dict = {}
        aj_m = _AJ_INIT_RE.search(html)
        if aj_m:
            try:
                aj_data = _json.loads(aj_m.group(1))
            except (_json.JSONDecodeError, ValueError):
                pass

        item_data = aj_data.get("item") or aj_data.get("lot") or {}

        def _ton(v) -> float:
            """Fragment embeds amounts as nanoton ints or TON floats — normalise."""
            if not v:
                return 0.0
            f = float(v)
            return f / 1_000_000_000 if f > 1_000_000 else f

        current_bid = _ton(item_data.get("bid") or item_data.get("price") or _PRICE_RE.search(html) and float(_PRICE_RE.search(html).group(1).replace(",", "")))
        min_next = _ton(item_data.get("min_bid") or item_data.get("minBid")) or round(current_bid * 1.05, 2)
        buy_now = _ton(item_data.get("buy_now") or item_data.get("buyNow")) or None
        auction_end_raw = item_data.get("ends_at") or item_data.get("endsAt")
        auction_end = int(auction_end_raw) if auction_end_raw else None
        if not auction_end:
            t_m = _TIMER_END_RE.search(html)
            auction_end = int(t_m.group(1)) if t_m else None

        name_m = _NAME_RE.search(html) or _DISPLAY_NAME_RE.search(html)
        name = name_m.group(1).strip() if name_m else slug

        img_m = _IMG_RE.search(html)
        image_url = _absolute_url(img_m.group(1)) if img_m else None

        return {
            "slug": slug,
            "item_type": item_type,
            "name": name,
            "current_bid": current_bid,
            "min_next_bid": min_next,
            "buy_now_price": buy_now if buy_now and buy_now != current_bid else None,
            "auction_end": auction_end,
            "url": url,
            "image_url": image_url,
        }

    async def list_gifts(self, collection_slug: str, limit: int = 60, sort: str = "price") -> list[GiftItem]:
        """Return currently available fixed-price gifts from one collection.

        sort: "price" / "price_asc" → cheapest first; "recent" → newest first.
        """
        if not 1 <= limit <= 200:
            raise FragmentCatalogError("limit must be between 1 and 200")
        _SORT_ALIASES = {"price_asc": "price", "price_desc": "price"}
        sort_param = _SORT_ALIASES.get(sort, sort)
        if sort_param not in {"price", "recent"}:
            raise FragmentCatalogError("sort must be 'price', 'price_asc', or 'recent'")
        url = f"{FRAGMENT_BASE}/gifts/{collection_slug}?sort={sort_param}&filter=sale"
        async with aiohttp.ClientSession(headers=self._headers(), timeout=REQUEST_TIMEOUT) as session:
            async with session.get(url) as response:
                response.raise_for_status()
                html = await response.text()
        items = _parse_items(html, collection_slug, limit)
        if not items:
            logger.warning(
                "list_gifts(%r): parsed 0 items from %d bytes of HTML — "
                "fragment.com markup may have changed (tm-grid-item / tm-grid-item-status)",
                collection_slug, len(html),
            )
        return items
