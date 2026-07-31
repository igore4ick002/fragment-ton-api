# fragment-ton-api

Unofficial async Python client for Fragment.com, TON payments, Telegram Stars, Telegram Premium gifts, and collectible Telegram gifts.

The client signs TON transactions locally. Your wallet mnemonic is not sent to Fragment or to any third-party server.

## Links

- GitHub: https://github.com/igore4ick002/fragment-ton-api
- Documentation: https://github.com/igore4ick002/fragment-ton-api#readme
- Issues: https://github.com/igore4ick002/fragment-ton-api/issues
- PyPI: https://pypi.org/project/fragment-ton-api/
- API reference: https://github.com/igore4ick002/fragment-ton-api/blob/main/docs/api.md
- Examples: https://github.com/igore4ick002/fragment-ton-api/tree/main/examples

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
- `anonymous=False`: the sender will be visible.

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
  },
  "error_code": "fragment_payment_error"
}
```

The method finds the user, creates the payment, signs the TON transaction, sends it to the network, and confirms the payment in Fragment.

## 2. Buy Telegram Premium Gifts

```python
result = await client.buy_premium_gift(
    username="@username",
    months=3,
    anonymous=True,
)
print(result)
```

Parameters:

- `username`: Premium gift recipient.
- `months`: usually `3`, `6`, or `12`.
- `anonymous`: whether to hide the sender.

Response format:

```json
{
  "success": true,
  "error": null
}
```

## 3. List Gift Collections and Gifts

The catalog does not require a wallet:

```python
from fragment_api import FragmentCatalog

catalog = FragmentCatalog()
collections = await catalog.list_collections()
print(collections)
```

Collection format:

```json
[
  {
    "slug": "lol-pop",
    "name": "Lol Pop",
    "url": "https://fragment.com/gifts/lol-pop"
  }
]
```

Get available fixed-price gifts:

```python
gifts = await catalog.list_gifts(
    collection_slug="lol-pop",
    limit=20,
    sort="price",
)
```

Gift item format:

```json
{
  "slug": "lol-pop-12345",
  "collection": "lol-pop",
  "number": 12345,
  "name": "Gift name",
  "price_ton": 1.5,
  "image_url": "https://fragment.com/file/preview.png",
  "url": "https://fragment.com/gift/lol-pop-12345",
  "status": "for_sale"
}
```

Use the `slug` value as `item_slug` or `owned_item_slug` in purchase and transfer methods.

Current catalog support is focused on fixed-price listings, not auctions.

## 4. Buy an NFT Gift by `item_slug`

```python
result = await client.buy_gift(
    item_slug="lol-pop-12345",
    bid_amount="1.5",
)
print(result)
```

Parameters:

- `item_slug`: concrete listing slug from `list_gifts()`.
- `bid_amount`: purchase amount in TON. Passing it as a string is recommended.

Example response:

```json
{
  "success": true,
  "error": null
}
```

After a successful purchase, the gift is assigned to the wallet connected to `FragmentClient`.

## 5. Transfer a Purchased Gift to a User

```python
result = await client.transfer_gift(
    owned_item_slug="lol-pop-12345",
    recipient_username="@username",
    anonymous=True,
)
print(result)
```

Parameters:

- `owned_item_slug`: slug of an already purchased gift.
- `recipient_username`: Telegram username of the recipient.
- `anonymous`: whether to hide the sender.

The method finds the recipient in Fragment, creates the transfer transaction, signs it with the TON wallet, and confirms the transfer.

## 6. Buy and Deliver a Gift in One Call

```python
result = await client.buy_and_deliver_gift(
    item_slug="lol-pop-12345",
    bid_amount="1.5",
    recipient_username="@username",
    anonymous=True,
)
print(result)
```

The method performs two steps:

1. Buys the gift for the connected wallet.
2. Transfers the gift to the selected Telegram user.

If purchase succeeds but transfer fails, the gift may already be on the sender wallet. Do not buy it again blindly; retry delivery with `transfer_gift()` first.

## 7. Check TON Balance

```python
balance, error = await client.get_balance_ton()

if error:
    print("Error:", error)
else:
    print("Balance:", balance, "TON")
```

Successful result:

```python
(12.345, None)
```

Error result:

```python
(None, "error description")
```

Before buying anything, make sure the wallet has enough TON for the gift price and network fees.

## Security

Never publish these values in GitHub, README files, examples, logs, screenshots, or issue reports:

- 24-word TON wallet mnemonic.
- Fragment cookies.
- TonCenter API key.
- PyPI tokens.
- `.env` files and local databases.

This package uses Fragment web endpoints, not an official stable public Fragment API. Fragment may change HTML, endpoints, or authorization requirements at any time.

## Disclaimer

This is an unofficial project. It is not affiliated with Telegram, Fragment, TON Foundation, or PyPI.

## More

- API reference: [docs/api.md](docs/api.md)
- Ready-to-run examples: [examples/](examples/)
- Basic tests: [tests/](tests/)
