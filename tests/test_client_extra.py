"""Further network-facing coverage for FragmentClient: detect_wallet_version,
_load_premium_context/_load_gift_context, _get_link_with_reconnect retry
logic, and get_balance_ton for both wallet versions."""

import pytest

from fragment_api.client import (
    FragmentClient,
    WALLET_V4R2,
    WALLET_V5R1,
    detect_wallet_version,
)
from fragment_api.exceptions import FragmentError

MNEMONIC_V5 = " ".join(["word"] * 24)
# Must pass tonsdk's checksum validation (unlike the v5r1 placeholder above).
MNEMONIC_V4 = (
    "open relax decide produce rubber inner summer slab humble essence type "
    "crater symbol lunch manage flush cause orphan smart argue bomb brown "
    "wild sentence"
)

PREMIUM_PAGE_HTML = """
<script>
ajInit({"apiUrl":"\\/api?hash=aaa111bbb222"});
Wallet.init({"ton_proof":"cafef00d"});
</script>
"""

GIFT_PAGE_HTML = """
<script>
ajInit({"apiUrl":"\\/api?hash=ccc333ddd444"});
Wallet.init({"ton_proof":"f00dcafe"});
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


def make_client(wallet_version=WALLET_V5R1):
    mnemonic = MNEMONIC_V5 if wallet_version == WALLET_V5R1 else MNEMONIC_V4
    return FragmentClient(mnemonic=mnemonic, wallet_version=wallet_version)


def _record_api_request(results):
    """results: list of return values, one per call (last value repeats if exhausted)."""
    calls = []

    async def _fake(method, data):
        calls.append((method, data))
        idx = min(len(calls) - 1, len(results) - 1)
        return results[idx]

    _fake.calls = calls
    return _fake


# ---------- detect_wallet_version ----------

def test_detect_wallet_version_rejects_short_mnemonic():
    with pytest.raises(FragmentError):
        detect_wallet_version("only a few words")


def test_detect_wallet_version_returns_both_candidates_without_expected_address():
    result = detect_wallet_version(MNEMONIC_V4)
    assert result["matched"] is None
    assert set(result["candidates"]) == {WALLET_V5R1, WALLET_V4R2}
    assert result["candidates"][WALLET_V5R1].startswith(("UQ", "EQ"))
    assert result["candidates"][WALLET_V4R2].startswith(("UQ", "EQ"))


def test_detect_wallet_version_matches_expected_address():
    candidates = detect_wallet_version(MNEMONIC_V4)["candidates"]
    result = detect_wallet_version(MNEMONIC_V4, expected_address=candidates[WALLET_V4R2])
    assert result["matched"] == WALLET_V4R2


def test_detect_wallet_version_no_match_for_unrelated_address():
    result = detect_wallet_version(MNEMONIC_V4, expected_address="UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA6Nv")
    assert result["matched"] is None


# ---------- _load_premium_context / _load_gift_context ----------

@pytest.mark.asyncio
async def test_load_premium_context_parses_hash_and_sets_referer():
    client = make_client()
    client._session = FakeSession(get_responses=[FakeResponse(text=PREMIUM_PAGE_HTML)])

    await client._load_premium_context()

    assert client._api_hash == "aaa111bbb222"
    assert client._ton_proof_payload == "cafef00d"
    assert client._referer == "https://fragment.com/premium"
    assert client._connected is False


@pytest.mark.asyncio
async def test_load_premium_context_raises_when_hash_missing():
    client = make_client()
    client._session = FakeSession(get_responses=[FakeResponse(text="<html>nothing</html>")])

    with pytest.raises(FragmentError):
        await client._load_premium_context()


@pytest.mark.asyncio
async def test_load_gift_context_parses_hash_and_sets_referer():
    client = make_client()
    client._session = FakeSession(get_responses=[FakeResponse(text=GIFT_PAGE_HTML)])

    await client._load_gift_context("lol-pop-12345")

    assert client._api_hash == "ccc333ddd444"
    assert client._ton_proof_payload == "f00dcafe"
    assert client._referer == "https://fragment.com/gift/lol-pop-12345"
    assert client._connected is False


@pytest.mark.asyncio
async def test_load_gift_context_raises_when_hash_missing_includes_slug():
    client = make_client()
    client._session = FakeSession(get_responses=[FakeResponse(text="<html>nothing</html>")])

    with pytest.raises(FragmentError, match="lol-pop-12345"):
        await client._load_gift_context("lol-pop-12345")


# ---------- _get_link_with_reconnect ----------

@pytest.mark.asyncio
async def test_get_link_with_reconnect_succeeds_first_try_without_reconnecting():
    client = make_client()
    client._account = {"address": "x"}
    client._device = {"platform": "linux"}
    client._api_request = _record_api_request([{"transaction": {"messages": []}}])
    reconnect_calls = []
    client.connect_wallet = _mark_called(reconnect_calls)

    result = await client._get_link_with_reconnect("getBidLink", {"type": 5, "username": "slug"})

    assert result == {"transaction": {"messages": []}}
    assert len(client._api_request.calls) == 1
    assert reconnect_calls == []


@pytest.mark.asyncio
async def test_get_link_with_reconnect_reconnects_once_on_session_expired():
    client = make_client()
    client._account = {"address": "x"}
    client._device = {"platform": "linux"}
    client._connected = True
    client._ton_proof_payload = "old-payload"
    client._api_request = _record_api_request([
        {"error": "Session expired. Please reconnect your wallet"},
        {"transaction": {"messages": []}},
    ])
    reconnect_calls = []
    client.connect_wallet = _mark_called(reconnect_calls)

    result = await client._get_link_with_reconnect("getNftTransferLink", {"id": 1})

    assert result == {"transaction": {"messages": []}}
    assert len(client._api_request.calls) == 2
    assert len(reconnect_calls) == 1
    assert client._connected is False  # cleared before reconnect was invoked
    assert client._ton_proof_payload is None


@pytest.mark.asyncio
async def test_get_link_with_reconnect_does_not_retry_on_unrelated_error():
    client = make_client()
    client._account = {"address": "x"}
    client._device = {"platform": "linux"}
    client._api_request = _record_api_request([{"error": "insufficient funds"}])
    reconnect_calls = []
    client.connect_wallet = _mark_called(reconnect_calls)

    result = await client._get_link_with_reconnect("getBidLink", {"type": 5, "username": "slug"})

    assert result == {"error": "insufficient funds"}
    assert len(client._api_request.calls) == 1
    assert reconnect_calls == []


def _mark_called(calls_list):
    async def _fake():
        calls_list.append(True)
    return _fake


# ---------- get_balance_ton ----------

@pytest.mark.asyncio
async def test_get_balance_ton_v5_returns_balance_from_lite_balancer():
    client = make_client(WALLET_V5R1)

    class FakeBalance:
        grams = 5_000_000_000  # 5 TON

    class FakeStorage:
        balance = FakeBalance()

    class FakeAccount:
        storage = FakeStorage()

    class FakeBalancer:
        async def raw_get_account_state(self, address):
            return FakeAccount(), None

    async def fake_get_lite_balancer():
        return FakeBalancer()

    client._get_lite_balancer = fake_get_lite_balancer

    balance, error = await client.get_balance_ton()

    assert error is None
    assert balance == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_get_balance_ton_v5_returns_zero_for_uninitialized_wallet():
    client = make_client(WALLET_V5R1)

    class FakeBalancer:
        async def raw_get_account_state(self, address):
            return None, None

    async def fake_get_lite_balancer():
        return FakeBalancer()

    client._get_lite_balancer = fake_get_lite_balancer

    balance, error = await client.get_balance_ton()

    assert balance == 0.0
    assert error is None


@pytest.mark.asyncio
async def test_get_balance_ton_v5_returns_error_string_on_exception():
    client = make_client(WALLET_V5R1)

    async def fake_get_lite_balancer():
        raise RuntimeError("liteserver unreachable")

    client._get_lite_balancer = fake_get_lite_balancer

    balance, error = await client.get_balance_ton()

    assert balance is None
    assert error == "liteserver unreachable"


@pytest.mark.asyncio
async def test_get_balance_ton_v4_success():
    client = make_client(WALLET_V4R2)
    client._session = FakeSession(get_responses=[
        FakeResponse(json_data={"ok": True, "result": "3000000000"}),
    ])

    balance, error = await client.get_balance_ton()

    assert error is None
    assert balance == pytest.approx(3.0)


@pytest.mark.asyncio
async def test_get_balance_ton_v4_returns_error_when_not_ok():
    client = make_client(WALLET_V4R2)
    client._session = FakeSession(get_responses=[
        FakeResponse(json_data={"ok": False, "error": "unknown address"}),
    ])

    balance, error = await client.get_balance_ton()

    assert balance is None
    assert error == "unknown address"


@pytest.mark.asyncio
async def test_get_balance_returns_typed_dataclass():
    client = make_client(WALLET_V4R2)
    client._session = FakeSession(get_responses=[
        FakeResponse(json_data={"ok": True, "result": "1000000000"}),
    ])

    result = await client.get_balance()

    assert result.balance == pytest.approx(1.0)
    assert result.error is None
