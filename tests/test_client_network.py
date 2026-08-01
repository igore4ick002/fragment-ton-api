"""Tests for the network-facing parts of FragmentClient: page/hash parsing,
_api_request retry-on-401 behaviour, TonProof connect_wallet, and the v4/v5
sign-and-broadcast paths. These are the parts most likely to break silently
if Fragment changes its HTML or API, and previously had no coverage."""

import json

import pytest

from fragment_api.client import FragmentClient, WALLET_V4R2, WALLET_V5R1
from fragment_api.exceptions import FragmentError

MNEMONIC_V5 = " ".join(["word"] * 24)
# Must pass tonsdk's checksum validation, unlike the v5r1 placeholder above.
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
    """Records calls and serves canned responses for .get()/.post() in order."""

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


@pytest.mark.asyncio
async def test_load_page_parses_api_hash_and_ton_proof():
    client = make_client()
    fake_session = FakeSession(get_responses=[FakeResponse(text=STARS_PAGE_HTML)])
    client._session = fake_session

    await client._load_page()

    assert client._api_hash == "abc123def456"
    assert client._ton_proof_payload == "deadbeef00"
    assert client._referer == "https://fragment.com/stars/buy"
    assert client._connected is False


@pytest.mark.asyncio
async def test_load_page_raises_when_hash_missing():
    client = make_client()
    fake_session = FakeSession(get_responses=[FakeResponse(text="<html>no hash here</html>")])
    client._session = fake_session

    with pytest.raises(FragmentError):
        await client._load_page()


@pytest.mark.asyncio
async def test_api_request_loads_page_first_when_no_hash_yet():
    client = make_client()
    fake_session = FakeSession(
        get_responses=[FakeResponse(text=STARS_PAGE_HTML)],
        post_responses=[FakeResponse(json_data={"ok": True}, status=200)],
    )
    client._session = fake_session

    result = await client._api_request("someMethod", {"foo": "bar"})

    assert result == {"ok": True}
    assert client._api_hash == "abc123def456"
    # posted to the hash obtained from the page load
    post_url, post_kwargs = fake_session.post_calls[0]
    assert post_url == "https://fragment.com/api?hash=abc123def456"
    assert post_kwargs["data"]["method"] == "someMethod"
    assert post_kwargs["data"]["foo"] == "bar"


@pytest.mark.asyncio
async def test_api_request_retries_once_on_401():
    client = make_client()
    client._api_hash = "stale-hash"
    client._referer = "https://fragment.com/stars/buy"

    fake_session = FakeSession(
        get_responses=[FakeResponse(text=STARS_PAGE_HTML)],
        post_responses=[
            FakeResponse(status=401, json_data={"error": "unauthorized"}),
            FakeResponse(status=200, json_data={"ok": True}),
        ],
    )
    client._session = fake_session

    result = await client._api_request("someMethod", {})

    assert result == {"ok": True}
    assert client._api_hash == "abc123def456"
    assert len(fake_session.post_calls) == 2
    # first attempt used the stale hash, retry used the refreshed one
    assert fake_session.post_calls[0][0] == "https://fragment.com/api?hash=stale-hash"
    assert fake_session.post_calls[1][0] == "https://fragment.com/api?hash=abc123def456"


@pytest.mark.asyncio
async def test_connect_wallet_marks_connected_on_verified():
    client = make_client()
    client._ton_proof_payload = "deadbeef00"
    client._api_request = _record_api_request({"verified": True})

    await client.connect_wallet()

    assert client._connected is True
    method, data = client._api_request.calls[0]
    assert method == "checkTonProofAuth"
    account = json.loads(data["account"])
    device = json.loads(data["device"])
    proof = json.loads(data["proof"])
    assert account["address"] == client.raw_address
    assert account["publicKey"] == client.public_key.hex()
    assert device["appName"] == "tg-stars-bot-fragment-client"
    assert proof["payload"] == "deadbeef00"
    assert "signature" in proof


@pytest.mark.asyncio
async def test_connect_wallet_raises_when_not_verified():
    client = make_client()
    client._ton_proof_payload = "deadbeef00"
    client._api_request = _record_api_request({"verified": False, "error": "bad proof"})

    with pytest.raises(FragmentError):
        await client.connect_wallet()

    assert client._connected is False


@pytest.mark.asyncio
async def test_connect_wallet_loads_page_when_no_payload():
    client = make_client()
    assert client._ton_proof_payload is None

    async def fake_load_page():
        client._ton_proof_payload = "freshpayload"

    client._load_page = fake_load_page
    client._api_request = _record_api_request({"verified": True})

    await client.connect_wallet()

    assert client._connected is True
    _method, data = client._api_request.calls[0]
    proof = json.loads(data["proof"])
    assert proof["payload"] == "freshpayload"


def _record_api_request(return_value):
    calls = []

    async def _fake(method, data):
        calls.append((method, data))
        return return_value

    _fake.calls = calls
    return _fake


@pytest.mark.asyncio
async def test_sign_and_broadcast_v4_raises_on_multi_message_transaction():
    client = make_client(WALLET_V4R2)
    transaction = {"messages": [{"address": "a", "amount": "1"}, {"address": "b", "amount": "2"}]}

    with pytest.raises(FragmentError):
        await client._sign_and_broadcast_v4(transaction)


@pytest.mark.asyncio
async def test_sign_and_broadcast_v4_raises_when_toncenter_rejects_boc():
    client = make_client(WALLET_V4R2)

    class FakeBoc:
        def to_boc(self, has_idx):
            return b"\x00\x01"

    class FakeWallet:
        def create_transfer_message(self, to_addr, amount, seqno, payload):
            return {"message": FakeBoc()}

    client._tonsdk_wallet = FakeWallet()

    async def fake_get_seqno():
        return 0

    client._get_seqno_v4 = fake_get_seqno

    fake_session = FakeSession(
        post_responses=[FakeResponse(json_data={"ok": False, "error": "boc rejected"})]
    )
    client._session = fake_session

    with pytest.raises(FragmentError):
        await client._sign_and_broadcast_v4({"messages": [{"address": "EQabc", "amount": "1000"}]})


@pytest.mark.asyncio
async def test_sign_and_broadcast_v5_raises_on_multi_message_transaction():
    client = make_client(WALLET_V5R1)
    transaction = {"messages": [{"address": "a", "amount": "1"}, {"address": "b", "amount": "2"}]}

    with pytest.raises(FragmentError):
        await client._sign_and_broadcast_v5(transaction)
