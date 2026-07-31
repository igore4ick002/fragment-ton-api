import pytest

from fragment_api import FragmentClient


class DummyClient(FragmentClient):
    def __init__(self):
        pass

    async def buy_gift(self, item_slug, bid_amount):
        self.buy_args = (item_slug, bid_amount)
        return {"success": True, "error": None, "error_code": None}

    async def transfer_gift(self, owned_item_slug, recipient_username, anonymous=True):
        self.transfer_args = (owned_item_slug, recipient_username, anonymous)
        return {"success": True, "error": None, "error_code": None}


class FailingDeliveryClient(DummyClient):
    async def buy_gift(self, item_slug, bid_amount):
        return {
            "success": False,
            "error": {"code": "fragment_payment_error", "message": "already sold"},
            "error_code": "fragment_payment_error",
        }

    async def transfer_gift(self, owned_item_slug, recipient_username, anonymous=True):
        return {
            "success": False,
            "error": {"code": "fragment_transfer_error", "message": "not owned"},
            "error_code": "fragment_transfer_error",
        }


@pytest.mark.asyncio
async def test_buy_and_deliver_calls_purchase_then_transfer():
    client = DummyClient()

    result = await client.buy_and_deliver_gift("lol-pop-12345", "1.5", "@username", anonymous=False)

    assert result["success"] is True
    assert client.buy_args == ("lol-pop-12345", "1.5")
    assert client.transfer_args == ("lol-pop-12345", "@username", False)


@pytest.mark.asyncio
async def test_buy_and_deliver_returns_structured_error_when_both_steps_fail():
    client = FailingDeliveryClient()

    result = await client.buy_and_deliver_gift("lol-pop-12345", "1.5", "@username")

    assert result["success"] is False
    assert result["error_code"] == "fragment_transfer_error"
    assert result["error"]["details"]["purchase"]["code"] == "fragment_payment_error"
    assert result["error"]["details"]["transfer"]["code"] == "fragment_transfer_error"
