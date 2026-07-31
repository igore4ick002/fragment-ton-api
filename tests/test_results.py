import unittest

from fragment_api import (
    FragmentAuthError,
    FragmentCatalogError,
    FragmentPaymentError,
    FragmentWalletError,
)
from fragment_api.exceptions import error_result, success_result


class ResultFormatTests(unittest.TestCase):
    def test_success_result_format(self):
        self.assertEqual(
            success_result(),
            {"success": True, "error": None, "error_code": None},
        )

    def test_error_result_format(self):
        result = error_result("payment failed", default_code=FragmentPaymentError)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "fragment_payment_error")
        self.assertEqual(result["error"]["code"], "fragment_payment_error")
        self.assertEqual(result["error"]["message"], "payment failed")

    def test_exception_to_dict_with_details(self):
        error = FragmentAuthError("cookie required", details={"need_verify": True})

        self.assertEqual(
            error.to_dict(),
            {
                "code": "fragment_auth_error",
                "message": "cookie required",
                "details": {"need_verify": True},
            },
        )

    def test_exported_error_classes_have_codes(self):
        self.assertEqual(FragmentWalletError.code, "fragment_wallet_error")
        self.assertEqual(FragmentCatalogError.code, "fragment_catalog_error")


if __name__ == "__main__":
    unittest.main()
