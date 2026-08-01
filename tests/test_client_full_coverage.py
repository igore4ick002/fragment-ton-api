"""Closes the remaining coverage gaps in fragment_api.client: constructor
validation, cookie-jar wiring, both sign/broadcast happy paths, seqno
fetching, recipient search, the full buy_stars/buy_premium_gift/buy_gift/
transfer_gift branch matrix, and get_balance_ton edge cases."""

import base64
import logging

import pytest

from fragment_api.client import (
    FragmentClient,
    WALLET_V4R2,
    WALLET_V5R1,
    _lenient_b64decode,
)
from fragment_api.exceptions import FragmentError

MNEMONIC_V5 = " ".join(["word"] * 24)
MNEMONIC_V4 = (
    "open relax decide produce rubber inner summer slab humble essence type "
    "crater symbol lunch manage flush cause orphan smart argue bomb brown "
    "wild sentence"
)

STARS_PAGE_HTML = """
<script>
ajInit({"apiUrl":"\\/api?hash=abc123def456"});
Wallet.init({"ton_proof":"deadbeef00"});
</script>
"""
NO_PROOF_HTML = """
<script>
ajInit({"apiUrl":"\\/api?hash=abc123def456"});
</script>
"""


class FakeResponse:
    def __init__(self, *, text=None, json_data=None, status=200):
        self._text = text
        self._json_data = json_data
        self.status = status

    async def text(self):
        return self._text

    async def json(self):
        return self._json_data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, get_responses=None, post_responses=None):
        self.get_responses = list(get_responses or [])
        self.post_responses = list(post_responses or [])
        self.get_calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.get_responses.pop(0)

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_responses.pop(0)


def make_client(wallet_version=WALLET_V5R1, **kwargs):
    mnemonic = MNEMONIC_V5 if wallet_version == WALLET_V5R1 else MNEMONIC_V4
    return FragmentClient(mnemonic=mnemonic, wallet_version=wallet_version, **kwargs)


def _queue(*values):
    """Return an async function that yields `values` in order, one per call."""
    calls = []

    async def _fake(*args, **kwargs):
        calls.append((args, kwargs))
        idx = min(len(calls) - 1, len(values) - 1)
        return values[idx]

    _fake.calls = calls
    return _fake


def _noop_async(*_a, **_kw):
    async def _fake(*args, **kwargs):
        return None
    return _fake


# ---------- _lenient_b64decode ----------

def test_lenient_b64decode_handles_urlsafe_and_missing_padding():
    raw = b"hello world, this is a test payload"
    urlsafe_no_pad = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    assert _lenient_b64decode(urlsafe_no_pad) == raw


def test_lenient_b64decode_handles_standard_base64():
    raw = b"abc"
    standard = base64.b64encode(raw).decode()
    assert _lenient_b64decode(standard) == raw


# ---------- constructor validation ----------

def test_constructor_rejects_wrong_word_count():
    with pytest.raises(FragmentError):
        FragmentClient(mnemonic="only a few words")


# ---------- _get_session cookie wiring ----------

@pytest.mark.asyncio
async def test_get_session_parses_and_applies_cookies():
    client = make_client(fragment_cookies="stel_ssid=abc123; stel_token=def456")
    try:
        session = await client._get_session()
        cookies = {c.key: c.value for c in session.cookie_jar}
        assert cookies["stel_ssid"] == "abc123"
        assert cookies["stel_token"] == "def456"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_get_session_without_cookies_has_empty_jar():
    client = make_client()
    try:
        session = await client._get_session()
        assert list(session.cookie_jar) == []
    finally:
        await client.close()


# ---------- _load_page: missing ton_proof warning ----------

@pytest.mark.asyncio
async def test_load_page_warns_when_ton_proof_missing(caplog):
    client = make_client()
    client._session = FakeSession(get_responses=[FakeResponse(text=NO_PROOF_HTML)])

    with caplog.at_level(logging.WARNING):
        await client._load_page()

    assert client._api_hash == "abc123def456"
    assert client._ton_proof_payload is None
    assert any("no ton_proof payload" in rec.message for rec in caplog.records)


# ---------- _api_request 401 retry via gift/premium context ----------

@pytest.mark.asyncio
async def test_api_request_retries_via_gift_context_on_401():
    client = make_client()
    client._api_hash = "stale"
    client._referer = "https://fragment.com/gift/lol-pop-12345"

    fake_session = FakeSession(
        get_responses=[FakeResponse(text=STARS_PAGE_HTML)],
        post_responses=[
            FakeResponse(status=401, json_data={"error": "unauthorized"}),
            FakeResponse(status=200, json_data={"ok": True}),
        ],
    )
    client._session = fake_session

    result = await client._api_request("getBidLink", {})

    assert result == {"ok": True}
    # the reload GET must have hit the gift page, not /stars/buy
    assert "/gift/lol-pop-12345" in fake_session.get_calls[0][0]


@pytest.mark.asyncio
async def test_api_request_retries_via_premium_context_on_401():
    client = make_client()
    client._api_hash = "stale"
    client._referer = "https://fragment.com/premium"

    fake_session = FakeSession(
        get_responses=[FakeResponse(text=STARS_PAGE_HTML)],
        post_responses=[
            FakeResponse(status=401, json_data={"error": "unauthorized"}),
            FakeResponse(status=200, json_data={"ok": True}),
        ],
    )
    client._session = fake_session

    result = await client._api_request("initGiftPremiumRequest", {})

    assert result == {"ok": True}
    assert fake_session.get_calls[0][0] == "https://fragment.com/premium"


# ---------- _get_state_init_b64 (v4r2 branch) ----------

def test_get_state_init_b64_v4r2():
    client = make_client(WALLET_V4R2)
    encoded = client._get_state_init_b64()
    assert isinstance(encoded, str)
    assert len(encoded) > 0


# ---------- connect_wallet: still no payload after reload ----------

@pytest.mark.asyncio
async def test_connect_wallet_raises_when_payload_still_missing_after_reload():
    client = make_client()

    async def fake_load_page():
        pass  # never sets _ton_proof_payload

    client._load_page = fake_load_page

    with pytest.raises(FragmentError, match="ton_proof payload"):
        await client.connect_wallet()


# ---------- search_recipient / search_premium_recipient ----------

@pytest.mark.asyncio
async def test_search_recipient_success():
    client = make_client()
    client._api_request = _queue({"found": {"recipient": "tok"}})
    found = await client.search_recipient("@user", 50)
    assert found == {"recipient": "tok"}


@pytest.mark.asyncio
async def test_search_recipient_raises_on_api_error():
    client = make_client()
    client._api_request = _queue({"error": "boom"})
    with pytest.raises(FragmentError):
        await client.search_recipient("@user", 50)


@pytest.mark.asyncio
async def test_search_recipient_raises_when_not_found():
    client = make_client()
    client._api_request = _queue({"found": None})
    with pytest.raises(FragmentError):
        await client.search_recipient("@user", 50)


@pytest.mark.asyncio
async def test_search_premium_recipient_success():
    client = make_client()
    client._api_request = _queue({"found": {"recipient": "tok"}})
    found = await client.search_premium_recipient("@user", 3)
    assert found == {"recipient": "tok"}


@pytest.mark.asyncio
async def test_search_premium_recipient_raises_on_api_error():
    client = make_client()
    client._api_request = _queue({"error": "boom"})
    with pytest.raises(FragmentError):
        await client.search_premium_recipient("@user", 3)


@pytest.mark.asyncio
async def test_search_premium_recipient_raises_when_not_found():
    client = make_client()
    client._api_request = _queue({"found": None})
    with pytest.raises(FragmentError):
        await client.search_premium_recipient("@user", 3)


# ---------- _get_lite_balancer ----------

@pytest.mark.asyncio
async def test_get_lite_balancer_creates_and_starts_once(monkeypatch):
    client = make_client()

    class FakeBalancer:
        def __init__(self):
            self.started = False

        async def start_up(self):
            self.started = True

    fake_instance = FakeBalancer()

    class FakeLiteBalancer:
        @staticmethod
        def from_mainnet_config(trust_level):
            return fake_instance

    monkeypatch.setattr("pytoniq.LiteBalancer", FakeLiteBalancer)

    balancer = await client._get_lite_balancer()

    assert balancer is fake_instance
    assert fake_instance.started is True


# ---------- _sign_and_broadcast_v5 happy path ----------

@pytest.mark.asyncio
async def test_sign_and_broadcast_v5_happy_path(monkeypatch):
    client = make_client(WALLET_V5R1)

    class FakeWallet:
        def __init__(self):
            self.transfer_calls = []

        async def transfer(self, destination, amount, body):
            self.transfer_calls.append((destination, amount, body))

    fake_wallet = FakeWallet()

    async def fake_from_private_key(provider, private_key, wc=0, network_global_id=None, **kwargs):
        return fake_wallet

    from pytoniq.contract.wallets.wallet_v5 import WalletV5R1
    monkeypatch.setattr(WalletV5R1, "from_private_key", fake_from_private_key)

    async def fake_get_lite_balancer():
        return object()

    client._get_lite_balancer = fake_get_lite_balancer

    transaction = {"messages": [{"address": client.wallet_address, "amount": "1000000"}]}
    result = await client._sign_and_broadcast_v5(transaction)

    assert result == "sent-via-liteserver"
    assert len(fake_wallet.transfer_calls) == 1


# ---------- _sign_and_broadcast_v4 payload branch + success ----------

@pytest.mark.asyncio
async def test_sign_and_broadcast_v4_success_with_payload(monkeypatch):
    client = make_client(WALLET_V4R2)

    class FakeBoc:
        def to_boc(self, has_idx):
            return b"\x00\x01\x02"

    class FakeCell:
        @staticmethod
        def one_from_boc(serialized_boc):
            return "decoded-cell"

    monkeypatch.setattr("tonsdk.boc.Cell", FakeCell)

    class FakeWallet:
        def create_transfer_message(self, to_addr, amount, seqno, payload):
            assert payload == "decoded-cell"
            return {"message": FakeBoc()}

    client._tonsdk_wallet = FakeWallet()

    async def fake_get_seqno():
        return 5

    client._get_seqno_v4 = fake_get_seqno
    client._session = FakeSession(post_responses=[FakeResponse(json_data={"ok": True})])

    transaction = {"messages": [{"address": "EQabc", "amount": "1000", "payload": "c29tZS1wYXlsb2Fk"}]}
    boc = await client._sign_and_broadcast_v4(transaction)

    assert isinstance(boc, str)
    assert len(boc) > 0


@pytest.mark.asyncio
async def test_sign_and_broadcast_v4_sends_api_key_header_to_toncenter(monkeypatch):
    client = make_client(WALLET_V4R2, toncenter_api_key="secret-key")

    class FakeBoc:
        def to_boc(self, has_idx):
            return b"\x00"

    class FakeWallet:
        def create_transfer_message(self, to_addr, amount, seqno, payload):
            return {"message": FakeBoc()}

    client._tonsdk_wallet = FakeWallet()

    async def fake_get_seqno():
        return 0

    client._get_seqno_v4 = fake_get_seqno
    fake_session = FakeSession(post_responses=[FakeResponse(json_data={"ok": True})])
    client._session = fake_session

    await client._sign_and_broadcast_v4({"messages": [{"address": "EQabc", "amount": "1000"}]})

    _url, kwargs = fake_session.post_calls[0]
    assert kwargs["headers"]["X-API-Key"] == "secret-key"


# ---------- _get_seqno_v4 ----------

@pytest.mark.asyncio
async def test_get_seqno_v4_parses_stack_value():
    client = make_client(WALLET_V4R2)
    client._session = FakeSession(get_responses=[
        FakeResponse(json_data={"result": {"stack": [["num", "0x2a"]]}}),
    ])

    seqno = await client._get_seqno_v4()

    assert seqno == 42


@pytest.mark.asyncio
async def test_get_seqno_v4_falls_back_to_zero_on_malformed_response():
    client = make_client(WALLET_V4R2)
    client._session = FakeSession(get_responses=[
        FakeResponse(json_data={"unexpected": "shape"}),
    ])

    seqno = await client._get_seqno_v4()

    assert seqno == 0


@pytest.mark.asyncio
async def test_get_seqno_v4_sends_api_key_header():
    client = make_client(WALLET_V4R2, toncenter_api_key="secret-key")
    fake_session = FakeSession(get_responses=[
        FakeResponse(json_data={"result": {"stack": [["num", "0x1"]]}}),
    ])
    client._session = fake_session

    await client._get_seqno_v4()

    _url, kwargs = fake_session.get_calls[0]
    assert kwargs["headers"]["X-API-Key"] == "secret-key"


# ---------- buy_stars ----------

def _stub_common(client, *, connected=True):
    client._load_page = _noop_async()
    client._load_premium_context = _noop_async()
    client._load_gift_context = lambda *_a, **_kw: _noop_async()()
    client._connected = connected
    client._account = {"address": "x"}
    client._device = {"platform": "linux"}
    if not connected:
        async def fake_connect():
            client._connected = True
        client.connect_wallet = fake_connect
    else:
        client.connect_wallet = _noop_async()


@pytest.mark.asyncio
async def test_buy_stars_success_v5_with_confirm():
    client = make_client(WALLET_V5R1)
    _stub_common(client, connected=False)
    client.search_recipient = _queue({"recipient": "rcpt"})
    client._api_request = _queue(
        {"req_id": "r1"},
        {
            "transaction": {"messages": []},
            "confirm_method": "confirmBuyStars",
            "confirm_params": {"x": 1},
        },
        {"ok": True},
    )
    client._sign_and_broadcast_v5 = _queue("boc-data")

    result = await client.buy_stars("@user", 50, anonymous=True)

    assert result["success"] is True
    assert client._connected is True


@pytest.mark.asyncio
async def test_buy_stars_success_v4_without_confirm():
    client = make_client(WALLET_V4R2)
    _stub_common(client, connected=True)
    client.search_recipient = _queue({"recipient": "rcpt"})
    client._api_request = _queue(
        {"req_id": "r1"},
        {"transaction": {"messages": []}},
    )
    client._sign_and_broadcast_v4 = _queue("boc-data")

    result = await client.buy_stars("@user", 50, anonymous=False)

    assert result["success"] is True


@pytest.mark.asyncio
async def test_buy_stars_raises_when_need_ton():
    client = make_client()
    _stub_common(client)
    client.search_recipient = _queue({"recipient": "rcpt"})
    client._api_request = _queue({"need_ton": True})

    with pytest.raises(FragmentError):
        await client.buy_stars("@user", 50)


@pytest.mark.asyncio
async def test_buy_stars_returns_error_on_init_error():
    client = make_client()
    _stub_common(client)
    client.search_recipient = _queue({"recipient": "rcpt"})
    client._api_request = _queue({"error": "no funds"})

    result = await client.buy_stars("@user", 50)

    assert result["success"] is False
    assert result["error_code"] == "fragment_payment_error"


@pytest.mark.asyncio
async def test_buy_stars_returns_auth_error_on_need_verify():
    client = make_client()
    _stub_common(client)
    client.search_recipient = _queue({"recipient": "rcpt"})
    client._api_request = _queue({"req_id": "r1"}, {"need_verify": True})

    result = await client.buy_stars("@user", 50)

    assert result["success"] is False
    assert result["error_code"] == "fragment_auth_error"


@pytest.mark.asyncio
async def test_buy_stars_returns_error_on_link_error():
    client = make_client()
    _stub_common(client)
    client.search_recipient = _queue({"recipient": "rcpt"})
    client._api_request = _queue({"req_id": "r1"}, {"error": "gone"})

    result = await client.buy_stars("@user", 50)

    assert result["success"] is False
    assert result["error_code"] == "fragment_payment_error"


# ---------- buy_premium_gift ----------

@pytest.mark.asyncio
async def test_buy_premium_gift_success_v4_without_confirm():
    client = make_client(WALLET_V4R2)
    _stub_common(client)
    client.search_premium_recipient = _queue({"recipient": "rcpt"})
    client._api_request = _queue(
        {"req_id": "r1"},
        {"transaction": {"messages": []}},
    )
    client._sign_and_broadcast_v4 = _queue("boc-data")

    result = await client.buy_premium_gift("@user", 3)

    assert result["success"] is True


@pytest.mark.asyncio
async def test_buy_premium_gift_raises_when_need_ton():
    client = make_client()
    _stub_common(client)
    client.search_premium_recipient = _queue({"recipient": "rcpt"})
    client._api_request = _queue({"need_ton": True})

    with pytest.raises(FragmentError):
        await client.buy_premium_gift("@user", 3)


@pytest.mark.asyncio
async def test_buy_premium_gift_returns_error_on_init_error():
    client = make_client()
    _stub_common(client)
    client.search_premium_recipient = _queue({"recipient": "rcpt"})
    client._api_request = _queue({"error": "no funds"})

    result = await client.buy_premium_gift("@user", 3)

    assert result["success"] is False
    assert result["error_code"] == "fragment_payment_error"


@pytest.mark.asyncio
async def test_buy_premium_gift_returns_auth_error_on_need_verify():
    client = make_client()
    _stub_common(client)
    client.search_premium_recipient = _queue({"recipient": "rcpt"})
    client._api_request = _queue({"req_id": "r1"}, {"need_verify": True})

    result = await client.buy_premium_gift("@user", 3)

    assert result["success"] is False
    assert result["error_code"] == "fragment_auth_error"


@pytest.mark.asyncio
async def test_buy_premium_gift_returns_error_on_link_error():
    client = make_client()
    _stub_common(client)
    client.search_premium_recipient = _queue({"recipient": "rcpt"})
    client._api_request = _queue({"req_id": "r1"}, {"error": "gone"})

    result = await client.buy_premium_gift("@user", 3)

    assert result["success"] is False
    assert result["error_code"] == "fragment_payment_error"


@pytest.mark.asyncio
async def test_buy_premium_gift_connects_wallet_when_not_connected():
    client = make_client()
    _stub_common(client, connected=False)
    client.search_premium_recipient = _queue({"recipient": "rcpt"})
    client._api_request = _queue(
        {"req_id": "r1"},
        {"transaction": {"messages": []}},
    )
    client._sign_and_broadcast_v5 = _queue("boc-data")

    result = await client.buy_premium_gift("@user", 3)

    assert result["success"] is True
    assert client._connected is True


@pytest.mark.asyncio
async def test_buy_premium_gift_success_v5_with_confirm():
    client = make_client(WALLET_V5R1)
    _stub_common(client)
    client.search_premium_recipient = _queue({"recipient": "rcpt"})
    client._api_request = _queue(
        {"req_id": "r1"},
        {
            "transaction": {"messages": []},
            "confirm_method": "confirmGiftPremium",
            "confirm_params": {},
        },
        {"ok": True},
    )
    client._sign_and_broadcast_v5 = _queue("boc-data")

    result = await client.buy_premium_gift("@user", 6, anonymous=False)

    assert result["success"] is True


# ---------- buy_gift ----------

@pytest.mark.asyncio
async def test_buy_gift_success_v5_with_confirm():
    client = make_client(WALLET_V5R1)
    _stub_common(client)
    client._get_link_with_reconnect = _queue({
        "transaction": {"messages": []},
        "confirm_method": "confirmBid",
        "confirm_params": {},
    })
    client._api_request = _queue({"ok": True})
    client._sign_and_broadcast_v5 = _queue("boc-data")

    result = await client.buy_gift("lol-pop-12345", "1.5")

    assert result["success"] is True


@pytest.mark.asyncio
async def test_buy_gift_returns_auth_error_on_need_verify():
    client = make_client()
    _stub_common(client)
    client._get_link_with_reconnect = _queue({"need_verify": True})

    result = await client.buy_gift("lol-pop-12345", "1.5")

    assert result["success"] is False
    assert result["error_code"] == "fragment_auth_error"


@pytest.mark.asyncio
async def test_buy_gift_returns_error_on_link_error():
    client = make_client()
    _stub_common(client)
    client._get_link_with_reconnect = _queue({"error": "already sold"})

    result = await client.buy_gift("lol-pop-12345", "1.5")

    assert result["success"] is False
    assert result["error_code"] == "fragment_payment_error"


@pytest.mark.asyncio
async def test_buy_gift_success_v4_without_confirm():
    client = make_client(WALLET_V4R2)
    _stub_common(client)
    client._get_link_with_reconnect = _queue({"transaction": {"messages": []}})
    client._sign_and_broadcast_v4 = _queue("boc-data")

    result = await client.buy_gift("lol-pop-12345", "1.5")

    assert result["success"] is True


# ---------- transfer_gift ----------

@pytest.mark.asyncio
async def test_transfer_gift_success_v5_with_confirm():
    client = make_client(WALLET_V5R1)
    _stub_common(client)
    client._api_request = _queue(
        {"found": {"recipient": "rcpt"}},
        {"req_id": "r1"},
        {"ok": True},
    )
    client._get_link_with_reconnect = _queue({
        "transaction": {"messages": []},
        "confirm_method": "confirmTransfer",
        "confirm_params": {},
    })
    client._sign_and_broadcast_v5 = _queue("boc-data")

    result = await client.transfer_gift("lol-pop-12345", "@user")

    assert result["success"] is True


@pytest.mark.asyncio
async def test_transfer_gift_returns_error_when_recipient_search_fails():
    client = make_client()
    _stub_common(client)
    client._api_request = _queue({"error": "search down"})

    result = await client.transfer_gift("lol-pop-12345", "@user")

    assert result["success"] is False
    assert result["error_code"] == "fragment_recipient_error"


@pytest.mark.asyncio
async def test_transfer_gift_returns_error_when_recipient_not_found():
    client = make_client()
    _stub_common(client)
    client._api_request = _queue({"found": None})

    result = await client.transfer_gift("lol-pop-12345", "@user")

    assert result["success"] is False
    assert result["error_code"] == "fragment_recipient_error"


@pytest.mark.asyncio
async def test_transfer_gift_returns_error_on_init_error():
    client = make_client()
    _stub_common(client)
    client._api_request = _queue(
        {"found": {"recipient": "rcpt"}},
        {"error": "not owned"},
    )

    result = await client.transfer_gift("lol-pop-12345", "@user")

    assert result["success"] is False
    assert result["error_code"] == "fragment_transfer_error"


@pytest.mark.asyncio
async def test_transfer_gift_returns_auth_error_on_need_verify():
    client = make_client()
    _stub_common(client)
    client._api_request = _queue(
        {"found": {"recipient": "rcpt"}},
        {"req_id": "r1"},
    )
    client._get_link_with_reconnect = _queue({"need_verify": True})

    result = await client.transfer_gift("lol-pop-12345", "@user")

    assert result["success"] is False
    assert result["error_code"] == "fragment_auth_error"


@pytest.mark.asyncio
async def test_transfer_gift_returns_error_on_link_error():
    client = make_client()
    _stub_common(client)
    client._api_request = _queue(
        {"found": {"recipient": "rcpt"}},
        {"req_id": "r1"},
    )
    client._get_link_with_reconnect = _queue({"error": "gone"})

    result = await client.transfer_gift("lol-pop-12345", "@user")

    assert result["success"] is False
    assert result["error_code"] == "fragment_payment_error"


@pytest.mark.asyncio
async def test_transfer_gift_success_v4_without_confirm():
    client = make_client(WALLET_V4R2)
    _stub_common(client)
    client._api_request = _queue(
        {"found": {"recipient": "rcpt"}},
        {"req_id": "r1"},
    )
    client._get_link_with_reconnect = _queue({"transaction": {"messages": []}})
    client._sign_and_broadcast_v4 = _queue("boc-data")

    result = await client.transfer_gift("lol-pop-12345", "@user", anonymous=False)

    assert result["success"] is True


# ---------- buy_and_deliver_gift: failed buy but transfer already succeeds ----------

@pytest.mark.asyncio
async def test_buy_and_deliver_gift_returns_transfer_result_when_buy_failed_but_transfer_succeeds():
    client = make_client()

    async def failing_buy(item_slug, bid_amount):
        return {"success": False, "error": {"code": "fragment_payment_error", "message": "already sold"}, "error_code": "fragment_payment_error"}

    async def succeeding_transfer(owned_item_slug, recipient_username, anonymous=True):
        return {"success": True, "error": None, "error_code": None}

    client.buy_gift = failing_buy
    client.transfer_gift = succeeding_transfer

    result = await client.buy_and_deliver_gift("lol-pop-12345", "1.5", "@user")

    assert result["success"] is True


# ---------- get_balance_ton: toncenter api key header + exception branch ----------

@pytest.mark.asyncio
async def test_get_balance_ton_v4_sends_api_key_header():
    client = make_client(WALLET_V4R2, toncenter_api_key="secret-key")
    fake_session = FakeSession(get_responses=[
        FakeResponse(json_data={"ok": True, "result": "1000000000"}),
    ])
    client._session = fake_session

    await client.get_balance_ton()

    _url, kwargs = fake_session.get_calls[0]
    assert kwargs["headers"]["X-API-Key"] == "secret-key"


@pytest.mark.asyncio
async def test_get_balance_ton_v4_returns_error_string_on_exception():
    client = make_client(WALLET_V4R2)

    class ExplodingSession:
        def get(self, *a, **kw):
            raise RuntimeError("connection refused")

    client._session = ExplodingSession()

    balance, error = await client.get_balance_ton()

    assert balance is None
    assert error == "connection refused"


# ---------- close() ----------

@pytest.mark.asyncio
async def test_close_closes_session_and_lite_balancer():
    client = make_client()
    closed = {"session": False, "balancer": False}

    class FakeSessionObj:
        async def close(self):
            closed["session"] = True

    class FakeBalancer:
        async def close_all(self):
            closed["balancer"] = True

    client._session = FakeSessionObj()
    client._lite_balancer = FakeBalancer()

    await client.close()

    assert closed == {"session": True, "balancer": True}
    assert client._session is None
    assert client._lite_balancer is None


@pytest.mark.asyncio
async def test_close_swallows_lite_balancer_close_error():
    client = make_client()

    class FakeBalancer:
        async def close_all(self):
            raise RuntimeError("already down")

    client._lite_balancer = FakeBalancer()

    await client.close()  # must not raise

    assert client._lite_balancer is None


@pytest.mark.asyncio
async def test_close_is_noop_when_nothing_open():
    client = make_client()
    await client.close()  # must not raise
    assert client._session is None
