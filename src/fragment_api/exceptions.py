"""Typed exceptions and result helpers for fragment_api."""

from __future__ import annotations

from typing import Any


class FragmentError(Exception):
    """Base exception for all fragment_api errors."""

    code = "fragment_error"
    is_html: bool = False  # True → message contains safe HTML (e.g. <a href>)

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details is not None:
            data["details"] = self.details
        return data


class FragmentAPIError(FragmentError):
    code = "fragment_api_error"


class FragmentAuthError(FragmentError):
    code = "fragment_auth_error"


class FragmentWalletError(FragmentError):
    code = "fragment_wallet_error"


class FragmentRecipientError(FragmentError):
    code = "fragment_recipient_error"


class FragmentPaymentError(FragmentError):
    code = "fragment_payment_error"


class FragmentTransferError(FragmentError):
    code = "fragment_transfer_error"


class FragmentCatalogError(FragmentError):
    code = "fragment_catalog_error"


def as_fragment_error(error: Any, *, default_code: type[FragmentError] = FragmentAPIError) -> FragmentError:
    if isinstance(error, FragmentError):
        return error
    return default_code(str(error))


def error_result(error: Any, *, default_code: type[FragmentError] = FragmentAPIError) -> dict[str, Any]:
    fragment_error = as_fragment_error(error, default_code=default_code)
    return {
        "success": False,
        "error": fragment_error.to_dict(),
        "error_code": fragment_error.code,
    }


def success_result() -> dict[str, Any]:
    return {
        "success": True,
        "error": None,
        "error_code": None,
    }
