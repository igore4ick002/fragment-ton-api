# fragment-ton-api-fraga

Неофициальный асинхронный клиент для Fragment.com и TON.

Поддерживает:

- покупку Telegram Stars;
- покупку Premium-подарков;
- покупку NFT-подарка по `item_slug`;
- передачу купленного подарка пользователю;
- покупку и последующую передачу подарка;
- проверку баланса TON.

## Установка

```bash
pip install fragment-ton-api
```

## Пример

```python
import asyncio
from fragment_api import FragmentClient


async def main():
    client = FragmentClient(
        mnemonic="слово1 слово2 ... слово24",
        toncenter_api_key="optional-toncenter-key",
        # Cookie авторизованной сессии fragment.com, если Fragment требует вход Telegram
        fragment_cookies="stel_ssid=...; stel_token=...",
    )
    try:
        await client.connect_wallet()
        print(await client.buy_stars("@username", 50))
        print(await client.buy_premium_gift("@username", 3))
        print(await client.buy_gift("gift-slug-123", "1.5"))
        print(await client.transfer_gift("gift-slug-123", "@username"))
        print(await client.buy_and_deliver_gift("gift-slug-123", "1.5", "@username"))
        print(await client.get_balance_ton())
    finally:
        await client.close()


asyncio.run(main())
```

Никогда не публикуйте мнемонику, cookie или API-ключ в исходниках и репозитории.
Клиент использует внутренние web-endpoint'ы Fragment, поэтому их формат может измениться.

## Получение списка подарков

```python
from fragment_api import FragmentCatalog

catalog = FragmentCatalog()
collections = await catalog.list_collections()
gifts = await catalog.list_gifts(collections[0]["slug"], limit=20)
```

Каждый подарок возвращается как JSON-совместимый объект:

```json
{
  "slug": "collection-12345",
  "collection": "collection",
  "number": 12345,
  "name": "Gift name",
  "price_ton": 1.5,
  "image_url": "https://fragment.com/file/preview.png",
  "url": "https://fragment.com/gift/collection-12345",
  "status": "for_sale"
}
```
