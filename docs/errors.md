# Error Codes

Payment and transfer methods return structured errors:

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

## Codes

| Code | Exception | Meaning |
| --- | --- | --- |
| `fragment_error` | `FragmentError` | Base package error. |
| `fragment_api_error` | `FragmentAPIError` | Generic Fragment API or response error. |
| `fragment_auth_error` | `FragmentAuthError` | Missing or invalid Telegram session cookies on Fragment. |
| `fragment_wallet_error` | `FragmentWalletError` | Invalid mnemonic, wallet confirmation, TON proof, or TON broadcast problem. |
| `fragment_recipient_error` | `FragmentRecipientError` | Recipient search failed or no recipient was found. |
| `fragment_payment_error` | `FragmentPaymentError` | Stars, Premium, or NFT gift purchase failed. |
| `fragment_transfer_error` | `FragmentTransferError` | Gift transfer failed. |
| `fragment_catalog_error` | `FragmentCatalogError` | Invalid catalog arguments or catalog parsing issue. |

## Handling Errors

```python
result = await client.buy_stars("@username", 50)

if not result["success"]:
    print(result["error_code"])
    print(result["error"]["message"])
```

Exceptions are raised for setup and wallet-level failures. Result dictionaries are returned for Fragment operation failures.
