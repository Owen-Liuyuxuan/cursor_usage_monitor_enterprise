from __future__ import annotations

import base64
import hashlib
import unittest

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from cursor_usage_supervisor.errors import CursorUsageError
from cursor_usage_supervisor.safe_storage import (
    SEALED_PREFIX,
    decrypt_linux_os_crypt,
    is_sealed_token,
    unseal_access_token,
)


def seal_token(plaintext: str, password: str, prefix: bytes = b"v11") -> str:
    """Create a Linux OSCrypt envelope matching Cursor's on-disk format."""
    key = hashlib.pbkdf2_hmac("sha1", password.encode("utf-8"), b"saltysalt", 1, dklen=16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16), backend=default_backend())
    encryptor = cipher.encryptor()
    blob = prefix + encryptor.update(padded) + encryptor.finalize()
    return SEALED_PREFIX + base64.b64encode(blob).decode("ascii")


class SafeStorageTest(unittest.TestCase):
    def test_plaintext_token_is_returned_unchanged(self) -> None:
        self.assertEqual(unseal_access_token("eyJhbGciOiJub25lIn0.e30.sig"), "eyJhbGciOiJub25lIn0.e30.sig")
        self.assertFalse(is_sealed_token("eyJhbGciOiJub25lIn0.e30.sig"))

    def test_unseals_v11_blob_with_injected_password(self) -> None:
        token = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJhdXRoMHx1c2VyX3Rlc3QifQ.sig"
        sealed = seal_token(token, "unit-test-password")
        self.assertTrue(is_sealed_token(sealed))
        self.assertEqual(
            unseal_access_token(sealed, lookup_password=lambda: "unit-test-password"),
            token,
        )

    def test_v10_prefix_is_accepted(self) -> None:
        token = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJhdXRoMHx1c2VyX3Rlc3QifQ.sig"
        sealed = seal_token(token, "unit-test-password", prefix=b"v10")
        self.assertEqual(
            unseal_access_token(sealed, lookup_password=lambda: "unit-test-password"),
            token,
        )

    def test_wrong_password_is_a_safe_error(self) -> None:
        sealed = seal_token("eyJhbGciOiJub25lIn0.e30.sig", "correct")
        with self.assertRaisesRegex(CursorUsageError, "could not be decrypted"):
            unseal_access_token(sealed, lookup_password=lambda: "wrong")

    def test_missing_keyring_password_is_a_safe_error(self) -> None:
        sealed = seal_token("eyJhbGciOiJub25lIn0.e30.sig", "correct")
        with self.assertRaisesRegex(CursorUsageError, "sealed"):
            unseal_access_token(sealed, lookup_password=lambda: None)

    def test_malformed_envelope_is_a_safe_error(self) -> None:
        with self.assertRaisesRegex(CursorUsageError, "unrecognized sealed format"):
            unseal_access_token(SEALED_PREFIX + "%%%", lookup_password=lambda: "x")
        with self.assertRaisesRegex(CursorUsageError, "unrecognized sealed format"):
            decrypt_linux_os_crypt(b"nope", "x")


if __name__ == "__main__":
    unittest.main()
