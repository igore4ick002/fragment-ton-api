# Fragment Authentication

`fragment-ton-api` signs TON transactions locally, but Fragment may also require an authorized Telegram browser session.

Pass that session through `fragment_cookies`:

```python
client = FragmentClient(
    mnemonic="word1 word2 ... word24",
    fragment_cookies="stel_ssid=...; stel_token=...",
)
```

## How to Get Cookies

1. Open https://fragment.com in your browser.
2. Log in with Telegram on Fragment.
3. Open browser developer tools.
4. Go to the Application or Storage tab.
5. Open Cookies for `https://fragment.com`.
6. Copy the active Fragment cookies into one string.

```text
stel_ssid=...; stel_token=...
```

Cookie names can change. Copy the active Fragment session cookies that your browser sends to `fragment.com`.

## Environment Variables

The examples use:

```powershell
$env:FRAGMENT_TON_MNEMONIC="word1 word2 ... word24"
$env:FRAGMENT_COOKIES="stel_ssid=...; stel_token=..."
$env:TONCENTER_API_KEY="optional-api-key"
```

## Security

Never publish cookies, wallet mnemonics, API keys, PyPI tokens, or `.env` files. If a secret is exposed, revoke or rotate it immediately.
