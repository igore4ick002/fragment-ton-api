# Examples

All examples are in the `examples/` directory.

## Environment Setup

```powershell
$env:FRAGMENT_TON_MNEMONIC="word1 word2 ... word24"
$env:FRAGMENT_COOKIES="stel_ssid=...; stel_token=..."
$env:TONCENTER_API_KEY="optional-api-key"
```

## Buy Telegram Stars

```powershell
python examples/buy_stars.py
```

## Buy Telegram Premium

```powershell
python examples/buy_premium.py
```

## List Gift Collections and Gifts

```powershell
python examples/list_gifts.py
```

## Buy a Collectible Gift

Edit `item_slug` and `bid_amount` in:

```powershell
python examples/buy_gift.py
```

## Transfer a Gift

Edit `owned_item_slug` and `recipient_username` in:

```powershell
python examples/transfer_gift.py
```

## Notes

Do not run purchase examples with a real wallet until you have checked the target username, amount, gift slug, and TON balance.
