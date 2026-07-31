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
