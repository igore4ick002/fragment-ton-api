# fragment-ton-api

Unofficial async Python client for Fragment.com, TON payments, Telegram Stars, Telegram Premium gifts, collectible Telegram gifts, anonymous phone numbers, and Telegram usernames.

The client signs TON transactions locally. Your wallet mnemonic is not sent to Fragment or to any third-party server.

## Links

- GitHub: https://github.com/igore4ick002/fragment-ton-api
- PyPI: https://pypi.org/project/fragment-ton-api/
- Issues: https://github.com/igore4ick002/fragment-ton-api/issues

## Installation

```bash
pip install fragment-ton-api
```

## Basic Usage

```python
import asyncio
from fragment_api import FragmentClient


async def main():
    client = FragmentClient(
        mnemonic="word1 word2 ... word24",
        toncenter_api_key="API_KEY or None",
        fragment_cookies="stel_ssid=...; stel_token=...",
    )
    try:
        await client.connect_wallet()
        # Fragment operations go here.
    finally:
        await client.close()


asyncio.run(main())
```

`FragmentClient` parameters:

- `mnemonic`: exactly 24 words for the TON wallet.
- `toncenter_api_key`: optional TonCenter API key, useful for some v4r2 wallet operations.
- `wallet_version`: `"v5r1"` by default, or `"v4r2"`.
- `fragment_cookies`: cookies from an authorized Telegram session on fragment.com. Without cookies, Fragment may return `need_verify`.

---

## 1. Buy Telegram Stars

```python
result = await client.buy_stars(
    username="@username",
    quantity=50,
    anonymous=True,
)
print(result)
```

Parameters:

- `username`: recipient Telegram username, with or without `@`.
- `quantity`: number of Telegram Stars to buy.
- `anonymous=True`: the recipient will not see the sender.

Successful response:

```json
{
  "success": true,
  "error": null
}
```

Error response:

```json
{
  "success": false,
  "error": {
    "code": "fragment_payment_error",
    "message": "Fragment error description"
  }
}
```

---

## 2. Buy Telegram Premium Gift

```python
result = await client.buy_premium_gift(
    username="@username",
    months=3,
    anonymous=True,
)
```

Parameters:

- `username`: Premium gift recipient.
- `months`: `3`, `6`, or `12`.
- `anonymous`: whether to hide the sender.

---

## 3. NFT Gift Catalog

The catalog does not require a wallet or cookies:

```python
from fragment_api import FragmentCatalog

catalog = FragmentCatalog()
```

### List collections

```python
collections = await catalog.list_collections()
# [{"slug": "lol-pop", "name": "Lol Pop", "url": "...", "emoji": "🍭"}]
```

### List gifts in a collection

```python
gifts = await catalog.list_gifts(
    collection_slug="lol-pop",
    limit=20,
    sort="price",   # or "recent"
)
```

`GiftItem` fields: `slug`, `collection`, `number`, `name`, `price_ton`, `image_url`, `url`, `status`.

### Collection emoji

```python
from fragment_api import get_gift_emoji, COLLECTION_EMOJI

emoji = get_gift_emoji("lol-pop")   # "🍭"
all_emojis = COLLECTION_EMOJI       # {"lol-pop": "🍭", ...}
```

---

## 4. Buy an NFT Gift

```python
result = await client.buy_gift(item_slug="lol-pop-12345", bid_amount="1.5")
```

- `item_slug`: slug from `list_gifts()`.
- `bid_amount`: purchase amount in TON (string recommended).

---

## 5. Transfer a Gift

```python
result = await client.transfer_gift(
    owned_item_slug="lol-pop-12345",
    recipient_username="@username",
    anonymous=True,
)
```

---

## 6. Buy and Deliver a Gift in One Call

```python
result = await client.buy_and_deliver_gift(
    item_slug="lol-pop-12345",
    bid_amount="1.5",
    recipient_username="@username",
    anonymous=True,
)
```

If purchase succeeds but transfer fails, retry with `transfer_gift()` — do not buy again.

---

## 7. Anonymous Phone Numbers

Browse and buy anonymous Telegram phone numbers available on Fragment.

### List numbers

```python
from fragment_api import FragmentCatalog

catalog = FragmentCatalog()
numbers = await catalog.list_numbers(
    limit=50,
    sort="price",      # "price" (cheapest first) or "recent"
    filter="all",      # "all" | "sale" | "auction"
)
```

`filter` values:

| Value | Description |
|-------|-------------|
| `"all"` | Fixed-price and auction items combined |
| `"sale"` | Fixed-price only (buy now) |
| `"auction"` | Currently on auction only |

`NumberItem` fields:

```python
{
    "slug": "88800000001",
    "number": "+888 0000 0001",
    "price_ton": 100.0,
    "min_bid_ton": 105.0,    # minimum bid to outbid current leader
    "auction_end": 1790000000,  # unix timestamp, None for fixed-price
    "is_auction": False,
    "status": "for_sale",    # "for_sale" | "on_auction"
    "url": "https://fragment.com/number/88800000001",
}
```

### Buy a number (fixed price or place bid)

```python
result = await client.buy_number(
    number_slug="88800000001",
    bid_amount=100.0,
)
```

For fixed-price listings, `bid_amount` must equal the listed price. For auctions, it must be ≥ `min_bid_ton`.

---

## 8. Telegram Usernames

Browse and bid on Telegram usernames listed on Fragment.

### List usernames

```python
usernames = await catalog.list_usernames(
    limit=50,
    sort="price",
    filter="all",   # "all" | "auction"
)
```

`UsernameItem` fields:

```python
{
    "slug": "coolname",
    "username": "coolname",      # without @
    "price_ton": 420.0,
    "min_bid_ton": 441.0,
    "auction_end": 1790000000,
    "is_auction": True,
    "status": "on_auction",
    "url": "https://fragment.com/username/coolname",
}
```

> **Note:** Fragment currently lists usernames only via auction. Fixed-price username listings (`filter="sale"`) may return an empty list without authentication.

### Place a bid on a username

```python
result = await client.buy_username(
    username_slug="coolname",
    bid_amount=441.0,
)
```

---

## 9. Live Auction Info

Get the current bid, minimum next bid, buy-now price, and time remaining for any item:

```python
info = await catalog.get_auction_info(
    slug="lol-pop-12345",
    item_type="gift",   # "gift" | "number" | "username"
)
```

`AuctionInfo` fields:

```python
{
    "slug": "lol-pop-12345",
    "item_type": "gift",
    "name": "Lol Pop #12345",
    "current_bid": 10.0,
    "min_next_bid": 10.5,
    "buy_now_price": 15.0,   # None if not available
    "auction_end": 1790000000,
    "url": "https://fragment.com/gift/lol-pop-12345",
    "image_url": "https://nft.fragment.com/gift/lol-pop-12345.webp",
}
```

---

## 10. Check TON Balance

```python
balance, error = await client.get_balance_ton()

if error:
    print("Error:", error)
else:
    print("Balance:", balance, "TON")
```

---

## Security

Never publish these values in GitHub, README files, examples, logs, screenshots, or issue reports:

- 24-word TON wallet mnemonic.
- Fragment cookies (`stel_ssid`, `stel_token`, `stel_ton_token`).
- TonCenter API key.
- PyPI tokens or `.env` files.

This package uses Fragment web endpoints, not an official stable public Fragment API. Fragment may change HTML, endpoints, or authorization requirements at any time.

## Disclaimer

This is an unofficial project. It is not affiliated with Telegram, Fragment, TON Foundation, or PyPI.
