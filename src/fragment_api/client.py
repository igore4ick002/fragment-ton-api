# fragment_api.py
#
# Клиент к fragment.com "с нуля" — без сторонних Fragment-обёрток и без
# посреднических серверов (это принципиально: несколько популярных
# "неофициальных библиотек" на PyPI проксируют подпись через чужой
# домен fragment-api.tech — тут этого нет, все запросы идут только
# в fragment.com напрямую, кошелёк подписывает транзакции локально).
#
# Как это устроено (сверено вживую 2026-07-22 через сетевые запросы
# реальной страницы https://fragment.com/stars/buy):
#   1. GET /stars/buy — отдаёт HTML с ajInit({..., apiUrl: "/api?hash=XXXX"})
#      и Wallet.init({ton_proof: "<random_hex>", ...}) — hash и ton_proof
#      привязаны к cookie-сессии (stel_ssid), выдаются заново на каждый GET.
#   2. Все действия — POST на apiUrl с полем method:
#        - checkTonProofAuth  {account, device, proof} — подтверждает,
#          что мы владеем TON-кошельком (используется реальный TON Connect
#          "TonProof" протокол — открытый стандарт, не приватный для Fragment)
#        - searchStarsRecipient {query, quantity} — ищет получателя по @username
#        - initBuyStarsRequest  {recipient, quantity, payment_method:'ton'}
#          -> {need_ton:true} если кошелёк ещё не подтверждён, иначе {req_id, amount}
#        - getBuyStarsLink {id, show_sender, transaction:1}
#          -> {transaction: {...}, confirm_method, confirm_params}
#          show_sender=0  → анонимная покупка (получатель не видит, кто подарил)
#          show_sender=1  → покупка не анонимная
#   3. Транзакцию (TON transfer) подписываем и отправляем в сеть САМИ (локально,
#      мнемоника кошелька никуда не уходит), затем зовём confirm_method, чтобы
#      Fragment узнал, что платёж отправлен.
#
# Поддерживаются 2 версии контракта кошелька (адрес зависит от версии —
# одна и та же мнемоника даёт РАЗНЫЕ адреса для разных версий):
#   - "v5r1" — современный стандарт (Tonkeeper и т.д. по умолчанию с 2024), через pytoniq
#   - "v4r2" — старый стандарт, через tonsdk + публичный TonCenter API
# Версия определяется автоматически при подключении (detect_wallet_version).
#
# Требования:
#   - TON-кошелёк (24-словная мнемоника) с реальным балансом TON.
#     Настраивается через /admin -> "Fragment" (хранится в БД), либо через
#     переменную окружения FRAGMENT_TON_MNEMONIC как запасной вариант.
#   - pip install tonsdk pytoniq aiohttp

import asyncio
import base64
import hashlib
import json
import logging
import re
import time
from typing import Optional, Tuple

import aiohttp

from .exceptions import (
    FragmentAuthError,
    FragmentError,
    FragmentPaymentError,
    FragmentRecipientError,
    FragmentTransferError,
    FragmentWalletError,
    error_result,
    success_result,
)
from .types import BalanceResult, PaymentResult

logger = logging.getLogger(__name__)

FRAGMENT_BASE = "https://fragment.com"
TONCENTER_API = "https://toncenter.com/api/v2"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

WALLET_V4R2 = "v4r2"
WALLET_V5R1 = "v5r1"


def _lenient_b64decode(s: str) -> bytes:
    """Fragment иногда отдаёт base64 без паддинга и/или в url-safe алфавите — b64decode строгого Python на этом падает с 'Incorrect padding'."""
    s = s.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


# ---------- Отдельная сессия входа в Telegram-аккаунт на fragment.com ----------
# ВАЖНО: это НЕ сессия юзербота (Telethon/MTProto) — Fragment покупку звёзд
# подтверждает не только TON-кошельком, но и требует, чтобы на сайте был
# выполнен вход через Telegram (Login Widget), иначе отвечает
# {"need_verify": true, "error": "Unknown error"}. Эта сессия — обычные
# cookie браузера fragment.com после такого входа, хранятся отдельно от
# userbot_session.session и настраиваются через /admin -> Fragment.

def _derive_v4r2_address(words: list) -> str:
    from tonsdk.contract.wallet import Wallets, WalletVersionEnum
    _, _, _, wallet = Wallets.from_mnemonics(words, WalletVersionEnum.v4r2, workchain=0)
    return wallet.address.to_string(True, True, False)  # non-bounceable (UQ...), стандартный вид кошелька


def _derive_v5r1_address(words: list) -> str:
    from pytoniq.contract.wallets.wallet_v5 import WALLET_V5_R1_CODE, WalletV5R1
    from pytoniq_core import StateInit, Address
    from pytoniq_core.crypto.keys import mnemonic_to_private_key

    pub, _priv = mnemonic_to_private_key(words)
    data = WalletV5R1.create_data_cell(pub, wc=0, network_global_id=-239)
    state_init = StateInit(code=WALLET_V5_R1_CODE, data=data)
    addr = Address((0, state_init.serialize().hash))
    return addr.to_str(True, True, False)


def detect_wallet_version(mnemonic: str, expected_address: str = None) -> dict:
    """
    Определяет версию кошелька по мнемонике. Если передан expected_address (в любом
    формате UQ.../EQ...), возвращает ту версию, чей адрес совпадает; иначе — список
    всех вычисленных адресов для ручного сравнения администратором.
    """
    words = mnemonic.strip().split()
    if len(words) != 24:
        raise FragmentError("Мнемоника должна содержать ровно 24 слова")

    candidates = {
        WALLET_V5R1: _derive_v5r1_address(words),
        WALLET_V4R2: _derive_v4r2_address(words),
    }

    if expected_address:
        target = expected_address.strip()
        for version, addr in candidates.items():
            if addr == target:
                return {"matched": version, "candidates": candidates}
        return {"matched": None, "candidates": candidates}

    return {"matched": None, "candidates": candidates}


class FragmentClient:
    def __init__(
        self,
        mnemonic: str,
        toncenter_api_key: Optional[str] = None,
        wallet_version: str = WALLET_V5R1,
        fragment_cookies: Optional[str] = None,
    ):
        """
        mnemonic: 24 слова через пробел. НЕ хардкодить в коде.
        wallet_version: "v5r1" (современный, по умолчанию) или "v4r2" (старый стандарт).
        """
        words = mnemonic.strip().split()
        if len(words) != 24:
            raise FragmentError("Мнемоника должна содержать ровно 24 слова")

        self.mnemonic_words = words
        self.toncenter_api_key = toncenter_api_key
        self.wallet_version = wallet_version
        self.fragment_cookies = fragment_cookies

        if wallet_version == WALLET_V5R1:
            from pytoniq_core.crypto.keys import mnemonic_to_private_key
            pub_k, priv_k = mnemonic_to_private_key(words)
            self.public_key = pub_k
            self.private_key = priv_k
            self.wallet_address = _derive_v5r1_address(words)
            wc, hash_hex = self._parse_raw_from_friendly(self.wallet_address)
            self.raw_address = f"{wc}:{hash_hex}"
            self._tonsdk_wallet = None
        else:
            from tonsdk.contract.wallet import Wallets, WalletVersionEnum
            from tonsdk.crypto import mnemonic_to_wallet_key
            pub_k, priv_k = mnemonic_to_wallet_key(words)
            self.public_key = pub_k
            self.private_key = priv_k
            _mnemonics, _pub, _priv, self._tonsdk_wallet = Wallets.from_mnemonics(
                words, WalletVersionEnum.v4r2, workchain=0
            )
            self.wallet_address = self._tonsdk_wallet.address.to_string(True, True, False)
            self.raw_address = f"{self._tonsdk_wallet.address.wc}:{self._tonsdk_wallet.address.hash_part.hex()}"

        self._session: Optional[aiohttp.ClientSession] = None
        self._api_hash: Optional[str] = None
        self._ton_proof_payload: Optional[str] = None
        self._connected = False
        self._lite_balancer = None
        self._referer = f"{FRAGMENT_BASE}/stars/buy"

    @staticmethod
    def _parse_raw_from_friendly(friendly_address: str):
        from pytoniq_core import Address
        addr = Address(friendly_address)
        return addr.wc, addr.hash_part.hex()

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            jar = aiohttp.CookieJar()
            self._session = aiohttp.ClientSession(cookie_jar=jar, timeout=REQUEST_TIMEOUT)

            raw_cookies = self.fragment_cookies
            if raw_cookies:
                cookies = {}
                for part in raw_cookies.split(";"):
                    if "=" in part:
                        name, _, value = part.strip().partition("=")
                        cookies[name] = value
                if cookies:
                    from yarl import URL
                    self._session.cookie_jar.update_cookies(cookies, response_url=URL(FRAGMENT_BASE))
        return self._session

    async def _load_page(self):
        """Заходит на страницу покупки звёзд, получает свежий api hash + ton_proof payload + cookie-сессию."""
        session = await self._get_session()
        async with session.get(f"{FRAGMENT_BASE}/stars/buy?quantity=50") as resp:
            html = await resp.text()

        hash_match = re.search(r'"apiUrl":"\\?/api\?hash=([a-f0-9]+)"', html)
        proof_match = re.search(r'"ton_proof":"([a-f0-9]+)"', html)
        if not hash_match:
            raise FragmentError("Не удалось получить api hash со страницы fragment.com (сайт мог измениться)")

        self._api_hash = hash_match.group(1)
        self._ton_proof_payload = proof_match.group(1) if proof_match else None
        if proof_match is None:
            logger.warning("_load_page: got api hash but no ton_proof payload — connect_wallet() will fail later")
        self._referer = f"{FRAGMENT_BASE}/stars/buy"
        self._connected = False

    async def _load_premium_context(self):
        """Переключает клиента в контекст страницы Premium.

        Premium-подарки используют отдельные методы Fragment API
        (searchPremiumGiftRecipient/initGiftPremiumRequest/getGiftPremiumLink),
        и для них нужен api hash именно со страницы /premium.
        """
        session = await self._get_session()
        url = f"{FRAGMENT_BASE}/premium"
        async with session.get(url) as resp:
            html = await resp.text()

        hash_match = re.search(r'"apiUrl":"\\?/api\?hash=([a-f0-9]+)"', html)
        proof_match = re.search(r'"ton_proof":"([a-f0-9]+)"', html)
        if not hash_match:
            raise FragmentError("Не удалось получить api hash со страницы Premium")

        self._api_hash = hash_match.group(1)
        self._ton_proof_payload = proof_match.group(1) if proof_match else None
        self._referer = url
        self._connected = False

    async def _load_gift_context(self, item_slug: str):
        """Переключает клиента в контекст СТРАНИЦЫ ПОДАРКА (/gift/<slug>).

        Методы аукциона (getBidLink, getNftTransferLink) — это API страницы
        подарка: и api-hash, и ton_proof, и привязка подключённого кошелька у
        Fragment живут в контексте конкретной страницы. Если дёргать их с
        hash'ем страницы /stars/buy (как для звёзд), Fragment отвечает
        'Session expired. Please reconnect your wallet' — именно поэтому
        покупка звёзд работала, а покупка NFT-подарков падала."""
        session = await self._get_session()
        url = f"{FRAGMENT_BASE}/gift/{item_slug}"
        async with session.get(url) as resp:
            html = await resp.text()

        hash_match = re.search(r'"apiUrl":"\\?/api\?hash=([a-f0-9]+)"', html)
        proof_match = re.search(r'"ton_proof":"([a-f0-9]+)"', html)
        if not hash_match:
            raise FragmentError(f"Не удалось получить api hash со страницы подарка {item_slug}")

        self._api_hash = hash_match.group(1)
        self._ton_proof_payload = proof_match.group(1) if proof_match else None
        self._referer = url
        self._connected = False  # кошелёк надо подключить заново в этом контексте

    async def _api_request(self, method: str, data: dict) -> dict:
        if self._api_hash is None:
            await self._load_page()

        session = await self._get_session()
        payload = dict(data)
        payload["method"] = method

        url = f"{FRAGMENT_BASE}/api?hash={self._api_hash}"
        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self._referer,
        }
        async with session.post(url, data=payload, headers=headers) as resp:
            if resp.status == 401:
                # сессия истекла — обновляем hash и повторяем один раз
                if "/gift/" in self._referer:
                    await self._load_gift_context(self._referer.rsplit("/gift/", 1)[1])
                elif self._referer.rstrip("/").endswith("/premium"):
                    await self._load_premium_context()
                else:
                    await self._load_page()
                return await self._api_request(method, data)
            return await resp.json()

    # ---------- TonConnect "TonProof" — подтверждение владения кошельком ----------

    def _build_ton_proof_signature(self, domain: str, timestamp: int, payload: str) -> str:
        """Официальный формат TON Connect TonProof (открытый стандарт, не приватный API Fragment)."""
        wc, hash_hex = self._parse_raw_from_friendly(self.wallet_address)
        addr_hash = bytes.fromhex(hash_hex)
        wc_bytes = wc.to_bytes(4, "big", signed=True)

        domain_bytes = domain.encode("utf-8")
        message = (
            b"ton-proof-item-v2/"
            + wc_bytes
            + addr_hash
            + len(domain_bytes).to_bytes(4, "little")
            + domain_bytes
            + timestamp.to_bytes(8, "little")
            + payload.encode("utf-8")
        )
        full = b"\xff\xff" + b"ton-connect" + hashlib.sha256(message).digest()
        digest = hashlib.sha256(full).digest()

        from nacl.signing import SigningKey
        signing_key = SigningKey(self.private_key[:32])
        signature = signing_key.sign(digest).signature
        return base64.b64encode(signature).decode()

    def _get_state_init_b64(self) -> str:
        if self.wallet_version == WALLET_V5R1:
            from pytoniq.contract.wallets.wallet_v5 import WALLET_V5_R1_CODE, WalletV5R1
            from pytoniq_core import StateInit
            data = WalletV5R1.create_data_cell(self.public_key, wc=0, network_global_id=-239)
            state_init = StateInit(code=WALLET_V5_R1_CODE, data=data)
            return base64.b64encode(state_init.serialize().to_boc()).decode()
        else:
            state_init_cell = self._tonsdk_wallet.create_state_init()["state_init"]
            return base64.b64encode(state_init_cell.to_boc(False)).decode()

    async def connect_wallet(self):
        """Подтверждает владение кошельком перед Fragment (аналог 'Connect TON' на сайте)."""
        if self._ton_proof_payload is None:
            await self._load_page()
        if self._ton_proof_payload is None:
            raise FragmentError("Сайт не выдал ton_proof payload — не могу подтвердить кошелёк")

        timestamp = int(time.time())
        domain = "fragment.com"
        signature = self._build_ton_proof_signature(domain, timestamp, self._ton_proof_payload)

        account = {
            "address": self.raw_address,
            "chain": "-239",
            "walletStateInit": self._get_state_init_b64(),
            "publicKey": self.public_key.hex(),
        }
        device = {
            "platform": "linux",
            "appName": "tg-stars-bot-fragment-client",
            "appVersion": "1.0.0",
            "maxProtocolVersion": 2,
            "features": ["SendTransaction"],
        }
        proof = {
            "timestamp": timestamp,
            "domain": {"lengthBytes": len(domain), "value": domain},
            "signature": signature,
            "payload": self._ton_proof_payload,
        }

        result = await self._api_request("checkTonProofAuth", {
            "account": json.dumps(account),
            "device": json.dumps(device),
            "proof": json.dumps(proof),
        })

        if not result.get("verified"):
            raise FragmentError(f"Fragment не подтвердил кошелёк: {result.get('error', result)}")

        self._connected = True
        self._account = account
        self._device = device

    # ---------- Покупка звёзд ----------

    async def search_recipient(self, username: str, quantity: int) -> dict:
        result = await self._api_request("searchStarsRecipient", {
            "query": username.lstrip("@"),
            "quantity": quantity,
        })
        if result.get("error"):
            raise FragmentError(result["error"])
        found = result.get("found")
        if not found:
            raise FragmentError(f"Получатель @{username} не найден на Fragment")
        return found

    async def search_premium_recipient(self, username: str, months: int) -> dict:
        result = await self._api_request("searchPremiumGiftRecipient", {
            "query": username.lstrip("@"),
            "months": months,
        })
        if result.get("error"):
            raise FragmentError(result["error"])
        found = result.get("found")
        if not found:
            raise FragmentError(f"Получатель @{username} не найден на Fragment")
        return found

    async def _discard_lite_balancer(self):
        """Drops the cached LiteBalancer so the next call picks a fresh liteserver.
        Without this, a single flaky/misconfigured node in the trust_level=2 pool
        (e.g. one returning corrupt gas price config) stays cached forever and every
        subsequent call keeps failing against the same broken node."""
        if self._lite_balancer is not None:
            try:
                await self._lite_balancer.close_all()
            except Exception:
                pass
            self._lite_balancer = None

    async def _get_lite_balancer(self, trust_level: int = 2):
        if self._lite_balancer is not None:
            if getattr(self._lite_balancer, "_frag_trust_level", 2) != trust_level:
                await self._discard_lite_balancer()
        if self._lite_balancer is None:
            from pytoniq import LiteBalancer
            # start_up() может упасть с "no alive peers" при плохой сети —
            # повторяем до 3 раз с экспоненциальной задержкой
            last_err = None
            for attempt in range(3):
                if attempt:
                    await asyncio.sleep(2 ** attempt)
                try:
                    lb = LiteBalancer.from_mainnet_config(trust_level=trust_level)
                    await lb.start_up()
                    lb._frag_trust_level = trust_level
                    self._lite_balancer = lb
                    return self._lite_balancer
                except Exception as e:
                    last_err = e
                    logger.warning("LiteBalancer start_up attempt %d failed: %s", attempt + 1, e)
            raise FragmentWalletError(f"Не удалось подключиться ни к одному TON liteserver: {last_err}")
        return self._lite_balancer

    async def _get_wallet_state_toncenter(self) -> dict:
        """Диагностика кошелька через TonCenter: баланс и статус (active/uninitialized)."""
        session = await self._get_session()
        headers = {"X-API-Key": self.toncenter_api_key} if self.toncenter_api_key else {}
        try:
            async with session.get(
                f"{TONCENTER_API}/getAddressInformation",
                params={"address": self.wallet_address},
                headers=headers,
            ) as resp:
                data = await resp.json()
                result = data.get("result", {})
                return {
                    "balance": int(result.get("balance", 0)),
                    "state": result.get("state", "unknown"),
                }
        except Exception as ex:
            return {"balance": -1, "state": "unknown", "error": str(ex)}

    async def _sign_and_broadcast_v5(self, transaction: dict) -> str:
        from pytoniq.contract.wallets.wallet_v5 import WALLET_V5_R1_CODE, WalletV5R1
        from pytoniq_core import Address, Cell as CoreCell, StateInit
        from pytoniq_core.crypto.keys import mnemonic_to_private_key

        messages = transaction["messages"]
        if len(messages) != 1:
            raise FragmentError("Ожидалось одно сообщение в транзакции — формат Fragment мог измениться")
        msg = messages[0]
        body = CoreCell.empty() if not msg.get("payload") else CoreCell.one_from_boc(_lenient_b64decode(msg["payload"]))
        _pub, priv = mnemonic_to_private_key(self.mnemonic_words)

        # Всегда передаём stateInit — это безопасно для уже развёрнутых кошельков
        # и критически важно для первой транзакции с нового (ещё не активированного) адреса.
        # "rejected before smart-contract execution" = кошелёк не задеплоен → без stateInit
        # транзакция будет отклонена каждый раз.
        state_init = StateInit(
            code=WALLET_V5_R1_CODE,
            data=WalletV5R1.create_data_cell(self.public_key, wc=0, network_global_id=-239),
        )

        RETRY_PLAN = [(2, 0), (2, 2.0), (1, 4.0), (1, 6.0)]
        last_error = None
        for trust_level, sleep_sec in RETRY_PLAN:
            if sleep_sec:
                await asyncio.sleep(sleep_sec)
            try:
                balancer = await self._get_lite_balancer(trust_level=trust_level)
                wallet = await WalletV5R1.from_private_key(balancer, priv, wc=0, network_global_id=-239)
                await wallet.transfer(
                    destination=Address(msg["address"]),
                    amount=int(msg["amount"]),
                    body=body,
                    state_init=state_init,
                )
                return "sent-via-liteserver"
            except Exception as ex:
                last_error = ex
                logger.warning("v5 broadcast attempt failed (trust=%d): %s", trust_level, ex)
                await self._discard_lite_balancer()

        # Все попытки провалились — диагностируем и даём понятную ошибку
        ws = await self._get_wallet_state_toncenter()
        if ws.get("balance", -1) == 0:
            raise FragmentWalletError(
                f"TON-кошелёк пуст. Пополните адрес {self.wallet_address} "
                "и повторите попытку."
            )
        if ws.get("state") == "uninitialized":
            raise FragmentWalletError(
                f"Кошелёк не активирован ({self.wallet_address}). "
                "Отправьте хотя бы 0.05 TON на этот адрес для активации."
            )
        raise FragmentWalletError(
            f"Не удалось отправить транзакцию через TON liteserver: {last_error}"
        )

    async def _sign_and_broadcast_v4(self, transaction: dict) -> str:
        from tonsdk.boc import Cell

        messages = transaction["messages"]
        if len(messages) != 1:
            raise FragmentError("Ожидалось одно сообщение в транзакции — формат Fragment мог измениться")

        msg = messages[0]
        to_addr = msg["address"]
        amount = int(msg["amount"])
        body = None
        if msg.get("payload"):
            body = Cell.one_from_boc(_lenient_b64decode(msg["payload"]))

        seqno = await self._get_seqno_v4()
        query = self._tonsdk_wallet.create_transfer_message(
            to_addr=to_addr,
            amount=amount,
            seqno=seqno,
            payload=body,
        )
        boc = base64.b64encode(query["message"].to_boc(False)).decode()

        session = await self._get_session()
        headers = {"Content-Type": "application/json"}
        if self.toncenter_api_key:
            headers["X-API-Key"] = self.toncenter_api_key

        async with session.post(
            f"{TONCENTER_API}/sendBoc", json={"boc": boc}, headers=headers,
        ) as resp:
            result = await resp.json()
            if not result.get("ok"):
                raise FragmentError(f"Не удалось отправить транзакцию в сеть TON: {result}")

        return boc

    async def _get_seqno_v4(self) -> int:
        session = await self._get_session()
        headers = {}
        if self.toncenter_api_key:
            headers["X-API-Key"] = self.toncenter_api_key
        async with session.get(
            f"{TONCENTER_API}/runGetMethod",
            params={"address": self.wallet_address, "method": "seqno", "stack": "[]"},
            headers=headers,
        ) as resp:
            data = await resp.json()
            try:
                return int(data["result"]["stack"][0][1], 16)
            except Exception:
                return 0

    async def buy_stars(self, username: str, quantity: int, anonymous: bool = True) -> PaymentResult:
        """
        Покупает `quantity` звёзд для @username через Fragment, оплата с TON-кошелька.
        anonymous=True — получатель не увидит, кто подарил (show_sender=0).
        Возвращает {"success": bool, "error": str|None}.
        """
        await self._load_page()
        if not self._connected:
            await self.connect_wallet()

        found = await self.search_recipient(username, quantity)
        recipient_token = found["recipient"]

        init_result = await self._api_request("initBuyStarsRequest", {
            "recipient": recipient_token,
            "quantity": quantity,
            "payment_method": "ton",
        })
        if init_result.get("need_ton"):
            raise FragmentError("Fragment не подтвердил кошелёк (need_ton) — проверьте connect_wallet()")
        if init_result.get("error"):
            return error_result(init_result["error"], default_code=FragmentPaymentError)

        req_id = init_result["req_id"]

        link_result = await self._api_request("getBuyStarsLink", {
            "id": req_id,
            "show_sender": 0 if anonymous else 1,
            "transaction": 1,
            "account": json.dumps(self._account),
            "device": json.dumps(self._device),
        })
        if link_result.get("need_verify"):
            return error_result(FragmentAuthError("Fragment requires an authorized Telegram session cookie on fragment.com."))
        if link_result.get("error"):
            return error_result(link_result["error"], default_code=FragmentPaymentError)

        transaction = link_result["transaction"]
        if self.wallet_version == WALLET_V5R1:
            boc = await self._sign_and_broadcast_v5(transaction)
        else:
            boc = await self._sign_and_broadcast_v4(transaction)

        confirm_method = link_result.get("confirm_method")
        confirm_params = link_result.get("confirm_params", {})
        if confirm_method:
            await self._api_request(confirm_method, {
                "account": json.dumps(self._account),
                "device": json.dumps(self._device),
                "boc": boc,
                **confirm_params,
            })

        return success_result()

    async def buy_premium_gift(self, username: str, months: int, anonymous: bool = True) -> PaymentResult:
        """
        Покупает Telegram Premium Gift для @username через Fragment/TON.
        months: 3, 6 или 12.
        """
        await self._load_premium_context()
        if not self._connected:
            await self.connect_wallet()

        found = await self.search_premium_recipient(username, months)
        recipient_token = found["recipient"]

        init_result = await self._api_request("initGiftPremiumRequest", {
            "recipient": recipient_token,
            "months": months,
            "payment_method": "ton",
        })
        if init_result.get("need_ton"):
            raise FragmentError("Fragment не подтвердил кошелёк (need_ton) — проверьте connect_wallet()")
        if init_result.get("error"):
            return error_result(init_result["error"], default_code=FragmentPaymentError)

        req_id = init_result["req_id"]

        link_result = await self._api_request("getGiftPremiumLink", {
            "id": req_id,
            "show_sender": 0 if anonymous else 1,
            "transaction": 1,
            "account": json.dumps(self._account),
            "device": json.dumps(self._device),
        })
        if link_result.get("need_verify"):
            return error_result(FragmentAuthError("Fragment requires an authorized Telegram session cookie on fragment.com."))
        if link_result.get("error"):
            return error_result(link_result["error"], default_code=FragmentPaymentError)

        transaction = link_result["transaction"]
        boc = await (self._sign_and_broadcast_v5(transaction) if self.wallet_version == WALLET_V5R1
                     else self._sign_and_broadcast_v4(transaction))

        confirm_method = link_result.get("confirm_method")
        confirm_params = link_result.get("confirm_params", {})
        if confirm_method:
            await self._api_request(confirm_method, {
                "account": json.dumps(self._account),
                "device": json.dumps(self._device),
                "boc": boc,
                **confirm_params,
            })

        return success_result()

    # ---------- Покупка + передача уникальных (коллекционных) подарков ----------
    # Найдено вживую в js/auction.js на fragment.com — те же принципы, что buy_stars:
    # покупка (getBidLink, тип 5 = аукцион/лот подарка, "username" тут — это ID лота,
    # например "chillflame-109284", а не получатель), и ОТДЕЛЬНЫМ шагом — передача уже
    # купленного подарка другому Telegram-username (initNftTransferRequest -> getNftTransferLink),
    # тоже полностью через Fragment/TON, без Telegram MTProto/юзербота.

    async def _get_link_with_reconnect(self, method: str, params: dict) -> dict:
        """getBidLink/getNftTransferLink с автоматическим переподключением кошелька.
        Fragment иногда отвечает 'Session expired. Please reconnect your wallet' —
        серверная привязка кошелька к сессии протухает; в этом случае проходим
        checkTonProofAuth заново (со свежим ton_proof payload) и повторяем запрос."""
        link_result = {}
        for attempt in (1, 2):
            link_result = await self._api_request(method, {
                **params,
                "account": json.dumps(self._account),
                "device": json.dumps(self._device),
                # без transaction:1 Fragment идёт по старому QR-пути и требует
                # живую сессию кошелька ("Session expired...") — ровно так же
                # этот флаг шлёт их фронтенд (auction.js: Wallet.sendTransaction)
                # и наш рабочий поток покупки звёзд
                "transaction": 1,
            })
            err = (link_result.get("error") or "")
            if attempt == 1 and "session expired" in err.lower():
                self._connected = False
                self._ton_proof_payload = None  # заставит connect_wallet перезагрузить страницу за свежим payload
                await self.connect_wallet()
                continue
            break
        return link_result

    async def buy_gift(self, item_slug: str, bid_amount) -> PaymentResult:
        """Покупает конкретный лот (item_slug вида 'chillflame-109284') по цене bid_amount TON.
        Подарок приходит на аккаунт, привязанный к этому кошельку (Fragment не поддерживает
        доставку сразу на чужой username при покупке — только через transfer_gift ниже)."""
        # Аукционные методы работают только в контексте страницы самого подарка
        await self._load_gift_context(item_slug)
        await self.connect_wallet()

        link_result = await self._get_link_with_reconnect("getBidLink", {
            "type": 5,
            "username": item_slug,
            "bid": str(bid_amount),
        })
        if link_result.get("need_verify"):
            return error_result(FragmentAuthError("Fragment requires an authorized Telegram session cookie on fragment.com."))
        if link_result.get("error"):
            return error_result(link_result["error"], default_code=FragmentPaymentError)

        transaction = link_result["transaction"]
        boc = await (self._sign_and_broadcast_v5(transaction) if self.wallet_version == WALLET_V5R1
                     else self._sign_and_broadcast_v4(transaction))

        confirm_method = link_result.get("confirm_method")
        confirm_params = link_result.get("confirm_params", {})
        if confirm_method:
            await self._api_request(confirm_method, {
                "account": json.dumps(self._account),
                "device": json.dumps(self._device),
                "boc": boc,
                **confirm_params,
            })
        return success_result()

    async def transfer_gift(self, owned_item_slug: str, recipient_username: str, anonymous: bool = True) -> PaymentResult:
        """Передаёт УЖЕ купленный (лежащий на этом аккаунте) подарок другому @username.
        Полностью через Fragment/TON — initNftTransferRequest ищет получателя, getNftTransferLink
        отдаёт транзакцию передачи для подписи (тот же механизм, что при покупке)."""
        # Передача — тоже аукционный метод, требует контекст страницы подарка
        await self._load_gift_context(owned_item_slug)
        await self.connect_wallet()

        # Шаг 1: как на сайте — сначала резолвим юзернейм в внутренний токен
        # получателя (searchNftTransferRecipient -> found.recipient); сырой
        # юзернейм initNftTransferRequest не принимает ("No Telegram users found")
        search_result = await self._api_request("searchNftTransferRecipient", {
            "query": recipient_username.lstrip("@"),
        })
        if search_result.get("error"):
            return error_result(f"recipient search: {search_result['error']}", default_code=FragmentRecipientError)
        found = search_result.get("found") or {}
        recipient_token = found.get("recipient")
        if not recipient_token:
            return error_result(f"recipient @{recipient_username.lstrip('@')} was not found on Fragment", default_code=FragmentRecipientError)

        init_result = await self._api_request("initNftTransferRequest", {
            "recipient": recipient_token,
            "slug": owned_item_slug,
        })
        if init_result.get("error"):
            return error_result(init_result["error"], default_code=FragmentTransferError)

        req_id = init_result["req_id"]

        link_result = await self._get_link_with_reconnect("getNftTransferLink", {
            "id": req_id,
            "show_sender": 0 if anonymous else 1,
        })
        if link_result.get("need_verify"):
            return error_result(FragmentAuthError("Fragment requires an authorized Telegram session cookie on fragment.com."))
        if link_result.get("error"):
            return error_result(link_result["error"], default_code=FragmentPaymentError)

        transaction = link_result["transaction"]
        boc = await (self._sign_and_broadcast_v5(transaction) if self.wallet_version == WALLET_V5R1
                     else self._sign_and_broadcast_v4(transaction))

        confirm_method = link_result.get("confirm_method")
        confirm_params = link_result.get("confirm_params", {})
        if confirm_method:
            await self._api_request(confirm_method, {
                "account": json.dumps(self._account),
                "device": json.dumps(self._device),
                "boc": boc,
                **confirm_params,
            })
        return success_result()

    async def buy_and_deliver_gift(self, item_slug: str, bid_amount, recipient_username: str, anonymous: bool = True) -> PaymentResult:
        """Покупает лот и сразу передаёт указанному @username — оба шага через Fragment/TON."""
        buy_result = await self.buy_gift(item_slug, bid_amount)
        if not buy_result["success"]:
            # Покупка могла пройти в ПРОШЛОЙ попытке (TON уже списаны, подарок на
            # нашем аккаунте), а упасть только доставка — тогда повторная покупка
            # вернёт ошибку "уже продан". Пробуем передать в любом случае: если
            # подарок наш, передача пройдёт; если нет — вернём обе ошибки.
            transfer_result = await self.transfer_gift(item_slug, recipient_username, anonymous=anonymous)
            if transfer_result["success"]:
                return transfer_result
            return error_result(
                FragmentTransferError(
                    "gift purchase and delivery failed",
                    details={"purchase": buy_result.get("error"), "transfer": transfer_result.get("error")},
                )
            )
        return await self.transfer_gift(item_slug, recipient_username, anonymous=anonymous)

    async def get_balance_ton(self) -> float:
        """Баланс кошелька в TON. Возвращает float, бросает исключение при ошибке."""
        if self.wallet_version == WALLET_V5R1:
            from pytoniq_core import Address
            try:
                balancer = await self._get_lite_balancer()
                account, _shard_account = await balancer.raw_get_account_state(Address(self.wallet_address))
                if account is None:
                    return 0.0  # кошелёк ещё не активирован в сети — баланс 0
                return account.storage.balance.grams / 1_000_000_000
            except Exception as ex:
                await self._discard_lite_balancer()
                raise FragmentWalletError(f"Не удалось получить баланс: {ex}") from ex

        session = await self._get_session()
        headers = {}
        if self.toncenter_api_key:
            headers["X-API-Key"] = self.toncenter_api_key
        async with session.get(
            f"{TONCENTER_API}/getAddressBalance",
            params={"address": self.wallet_address},
            headers=headers,
        ) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise FragmentWalletError(data.get("error", f"HTTP {resp.status}"))
            return int(data["result"]) / 1_000_000_000

    async def get_balance(self) -> BalanceResult:
        """Return wallet balance as a typed dataclass (never raises)."""
        try:
            balance = await self.get_balance_ton()
            return BalanceResult(balance=balance, error=None)
        except Exception as ex:
            return BalanceResult(balance=None, error=str(ex))

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None
        if self._lite_balancer:
            try:
                await self._lite_balancer.close_all()
            except Exception:
                pass
            self._lite_balancer = None
