"""List Fragment gift collections and fixed-price gifts."""

import asyncio

from fragment_api import FragmentCatalog


async def main() -> None:
    catalog = FragmentCatalog()
    collections = await catalog.list_collections()
    print(collections)

    if collections:
        gifts = await catalog.list_gifts(collections[0]["slug"], limit=20, sort="price")
        print(gifts)


if __name__ == "__main__":
    asyncio.run(main())
