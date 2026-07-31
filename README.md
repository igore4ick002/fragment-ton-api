# fragment-ton-api

Неофициальный асинхронный Python-клиент для Fragment.com и TON. Клиент подписывает TON-транзакции локально: мнемоника не отправляется на Fragment или сторонний сервер.

## Ссылки

- GitHub: https://github.com/igore4ick002/fragment-ton-api
- Документация: https://github.com/igore4ick002/fragment-ton-api#readme
- Issues: https://github.com/igore4ick002/fragment-ton-api/issues
- PyPI: https://pypi.org/project/fragment-ton-api/

## Установка

```bash
pip install fragment-ton-api
```

## Подключение

```python
import asyncio
from fragment_api import FragmentClient


async def main():
    client = FragmentClient(
        mnemonic="слово1 слово2 ... слово24",
        toncenter_api_key="API_KEY или None",
        fragment_cookies="stel_ssid=...; stel_token=...",
    )
    try:
        await client.connect_wallet()
        # операции Fragment здесь
    finally:
        await client.close()


asyncio.run(main())
```

Параметры `FragmentClient`:

- `mnemonic` — ровно 24 слова TON-кошелька;
- `toncenter_api_key` — необязательный ключ TonCenter, нужен для некоторых операций кошелька v4r2;
- `wallet_version` — `"v5r1"` по умолчанию или `"v4r2"`;
- `fragment_cookies` — cookie авторизованной Telegram-сессии на fragment.com. Без неё Fragment иногда возвращает `need_verify`.

## 1. Покупка Telegram Stars

```python
result = await client.buy_stars(
    username="@username",
    quantity=50,
    anonymous=True,
)
print(result)
```

Параметры:

- `username` — Telegram username получателя, с `@` или без него;
- `quantity` — количество Stars;
- `anonymous=True` — получатель не увидит отправителя;
- `anonymous=False` — отправитель будет виден.

Успешный ответ:

```json
{
  "success": true,
  "error": null
}
```

Ответ с ошибкой:

```json
{
  "success": false,
  "error": "описание ошибки Fragment"
}
```

Метод находит пользователя, создаёт платёж, подписывает TON-транзакцию, отправляет её в сеть и подтверждает платёж в Fragment.

## 2. Покупка Premium-подарка

```python
result = await client.buy_premium_gift(
    username="@username",
    months=3,
    anonymous=True,
)
print(result)
```

Параметры:

- `username` — получатель Premium;
- `months` — обычно `3`, `6` или `12` месяцев;
- `anonymous` — показывать ли отправителя подарка.

Ответ имеет такой же формат:

```json
{
  "success": true,
  "error": null
}
```

## 3. Получение списка коллекций и подарков

Для каталога кошелёк не нужен:

```python
from fragment_api import FragmentCatalog

catalog = FragmentCatalog()
collections = await catalog.list_collections()
print(collections)
```

Коллекции:

```json
[
  {
    "slug": "lol-pop",
    "name": "Lol Pop",
    "url": "https://fragment.com/gifts/lol-pop"
  }
]
```

Получение доступных подарков с фиксированной ценой:

```python
gifts = await catalog.list_gifts(
    collection_slug="lol-pop",
    limit=20,
    sort="price",
)
```

Каждый подарок:

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

Именно значение `slug` передаётся в методы покупки и передачи. Сейчас каталог возвращает доступные fixed-price лоты, а не аукционные лоты.

## 4. Покупка NFT-подарка по item_slug

```python
result = await client.buy_gift(
    item_slug="lol-pop-12345",
    bid_amount="1.5",
)
print(result)
```

Параметры:

- `item_slug` — slug конкретного лота из `list_gifts()`;
- `bid_amount` — цена покупки в TON, лучше передавать строкой.

Пример ответа:

```json
{
  "success": true,
  "error": null
}
```

После успешной покупки подарок поступает на кошелёк, подключённый к `FragmentClient`.

## 5. Передача купленного подарка пользователю

```python
result = await client.transfer_gift(
    owned_item_slug="lol-pop-12345",
    recipient_username="@username",
    anonymous=True,
)
print(result)
```

Параметры:

- `owned_item_slug` — slug уже купленного подарка;
- `recipient_username` — Telegram username получателя;
- `anonymous` — скрыть или показать отправителя.

Метод сначала находит получателя в Fragment, затем создаёт транзакцию передачи, подписывает её TON-кошельком и подтверждает передачу.

## 6. Покупка и последующая передача одним методом

```python
result = await client.buy_and_deliver_gift(
    item_slug="lol-pop-12345",
    bid_amount="1.5",
    recipient_username="@username",
    anonymous=True,
)
print(result)
```

Метод выполняет два шага:

1. покупает подарок на подключённый кошелёк;
2. передаёт этот подарок указанному Telegram-пользователю.

Если покупка прошла, а передача не прошла, метод вернёт ошибку передачи. В таком случае подарок может уже находиться на кошельке отправителя — повторную покупку делать нельзя, сначала проверь передачу через `transfer_gift()`.

## 7. Проверка баланса TON

```python
balance, error = await client.get_balance_ton()

if error:
    print("Ошибка:", error)
else:
    print("Баланс:", balance, "TON")
```

Успешный результат:

```python
(12.345, None)
```

При ошибке:

```python
(None, "описание ошибки")
```

Перед покупками нужно проверить, что баланса хватает не только на цену подарка, но и на комиссии сети TON.

## Важная безопасность

Никогда не публикуйте в GitHub, README или исходниках:

- 24 слова TON-мнемоники;
- Fragment cookies;
- TonCenter API key;
- `.env` и базы данных.

Клиент использует web-endpoint'ы Fragment, а не официальный стабильный публичный API. Fragment может изменить HTML, методы или требования к авторизации.
