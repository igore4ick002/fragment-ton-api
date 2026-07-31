# API Reference

## Result Format

Payment and transfer methods return a dictionary:

| Field | Type | Description |
| --- | --- | --- |
| `success` | `bool` | `True` when the operation completed. |
| `error` | `dict | None` | Structured error object or `None`. |
| `error_code` | `str | None` | Stable machine-readable error code or `None`. |

Error object format:

| Field | Type | Description |
| --- | --- | --- |
| `code` | `str` | Error code such as `fragment_payment_error`. |
| `message` | `str` | Human-readable error message. |
| `details` | `Any` | Optional extra data. |

## Methods

| Method | Parameters | Returns | Description |
| --- | --- | --- | --- |
| `FragmentClient(...)` | `mnemonic`, `toncenter_api_key=None`, `wallet_version="v5r1"`, `fragment_cookies=None` | client | Creates a TON/Fragment client. |
| `connect_wallet()` | none | `dict` from Fragment | Connects the TON wallet to the current Fragment session. |
| `buy_stars()` | `username`, `quantity`, `anonymous=True` | result dict | Buys Telegram Stars for a user. |
| `buy_premium_gift()` | `username`, `months`, `anonymous=True` | result dict | Buys a Telegram Premium gift. |
| `buy_gift()` | `item_slug`, `bid_amount` | result dict | Buys a collectible Telegram gift by Fragment item slug. |
| `transfer_gift()` | `owned_item_slug`, `recipient_username`, `anonymous=True` | result dict | Transfers an owned collectible gift to a Telegram user. |
| `buy_and_deliver_gift()` | `item_slug`, `bid_amount`, `recipient_username`, `anonymous=True` | result dict | Buys a gift and then transfers it to the recipient. |
| `get_balance_ton()` | none | `(balance, error)` | Returns wallet balance in TON or an error string. |
| `close()` | none | `None` | Closes HTTP and TON lite client sessions. |
| `FragmentCatalog(...)` | `fragment_cookies=None` | catalog | Creates read-only catalog helper. |
| `list_collections()` | none | `list[dict]` | Lists available gift collections. |
| `list_gifts()` | `collection_slug`, `limit=60`, `sort="price"` | `list[dict]` | Lists available fixed-price gifts in a collection. |

## Exceptions

| Class | Code | When Used |
| --- | --- | --- |
| `FragmentError` | `fragment_error` | Base class for package errors. |
| `FragmentAPIError` | `fragment_api_error` | Generic Fragment API error. |
| `FragmentAuthError` | `fragment_auth_error` | Missing or invalid Fragment Telegram session cookies. |
| `FragmentWalletError` | `fragment_wallet_error` | Wallet, mnemonic, TON proof, or broadcast problems. |
| `FragmentRecipientError` | `fragment_recipient_error` | Recipient search or validation problems. |
| `FragmentPaymentError` | `fragment_payment_error` | Stars, Premium, or gift purchase problems. |
| `FragmentTransferError` | `fragment_transfer_error` | Gift transfer problems. |
| `FragmentCatalogError` | `fragment_catalog_error` | Catalog parameter or parsing problems. |
