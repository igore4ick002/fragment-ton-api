"""Public type definitions for fragment_api."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, TypedDict


class FragmentErrorDict(TypedDict, total=False):
    code: str
    message: str
    details: Any


class PaymentResult(TypedDict):
    success: bool
    error: Optional[FragmentErrorDict]
    error_code: Optional[str]


class CollectionItem(TypedDict):
    slug: str
    name: str
    url: str
    emoji: str


class NumberItem(TypedDict):
    slug: str
    number: str             # "+7 999 123 45 67"
    price_ton: float        # current bid or fixed price
    min_bid_ton: float      # minimum next bid
    auction_end: Optional[int]   # unix timestamp; None if fixed-price
    is_auction: bool
    status: str             # "on_auction" | "for_sale"
    url: str


class UsernameItem(TypedDict):
    slug: str
    username: str           # "coolname" (without @)
    price_ton: float
    min_bid_ton: float
    auction_end: Optional[int]
    is_auction: bool
    status: str
    url: str


class AuctionInfo(TypedDict):
    slug: str
    item_type: str          # "gift" | "number" | "username"
    name: str
    current_bid: float
    min_next_bid: float
    buy_now_price: Optional[float]
    auction_end: Optional[int]
    url: str
    image_url: Optional[str]


class GiftItem(TypedDict):
    slug: str
    collection: str
    number: int
    name: str
    price_ton: float
    image_url: Optional[str]
    url: str
    status: str


@dataclass(frozen=True)
class BalanceResult:
    balance: Optional[float]
    error: Optional[str] = None
    usd: Optional[float] = None
    rub: Optional[float] = None
    ton_price_usd: Optional[float] = None
    ton_price_rub: Optional[float] = None
