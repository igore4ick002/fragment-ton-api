"""Buy Telegram Stars with fragment-ton-api."""

import asyncio
import os

from fragment_api import FragmentClient


async def main() -> None:
    client = FragmentClient(
        mnemonic=os.environ["FRAGMENT_TON_MNEMONIC"],
        toncenter_api_key=os.getenv("TONCENTER_API_KEY"),
        fragment_cookies=os.getenv("FRAGMENT_COOKIES"),
    )
    try:
        result = await client.buy_stars("@username", quantity=50, anonymous=True)
        print(result)
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
