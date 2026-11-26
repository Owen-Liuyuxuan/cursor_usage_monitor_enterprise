"""Unseal Cursor Desktop tokens encrypted at rest with Electron safeStorage.

Cursor 3.27+ can store ``cursorAuth/accessToken`` as
``cursor-safe-storage:v1:`` plus base64 of a Chromium OSCrypt blob.  On
Ubuntu / GNOME the wrapping key is the libsecret item for application
``Cursor``.  The plaintext exists only in memory and is never logged.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Callable

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .errors import CursorUsageError

SEALED_PREFIX = "cursor-safe-storage:v1:"
_LINUX_SALT = b"saltysalt"
_LINUX_IV = b" " * 16
_LINUX_ITERATIONS = 1
_LINUX_KEY_BYTES = 16
_LIBSECRET_SCHEMA = "chrome_libsecret_os_crypt_password_v2"
_LIBSECRET_APPLICATION = "Cursor"

PasswordLookup = Callable[[], str | None]


def is_sealed_token(value: str) -> bool:
    """Return whether *value* is an Electron safeStorage envelope."""
    return value.startswith(SEALED_PREFIX)


def lookup_linux_os_crypt_password() -> str | None:
    """Read Cursor's Chromium OSCrypt password from the GNOME keyring."""
    try:
        import gi

        gi.require_version("Secret", "1")
        from gi.repository import Secret
    except (ImportError, ValueError) as error:
        raise CursorUsageError(
            "GNOME Secret Service is unavailable; cannot unlock the Cursor login"
        ) from error

    schema = Secret.Schema.new(
        _LIBSECRET_SCHEMA,
        Secret.SchemaFlags.NONE,
        {"application": Secret.SchemaAttributeType.STRING},
    )
    try:
        return Secret.password_lookup_sync(
            schema, {"application": _LIBSECRET_APPLICATION}, None
        )
    except Exception as error:
        raise CursorUsageError(
            "GNOME keyring could not be queried for the Cursor login"
        ) from error


def decrypt_linux_os_crypt(blob: bytes, password: str) -> bytes:
    """Decrypt a Chromium ``v10``/``v11`` AES-128-CBC OSCrypt payload."""
    if len(blob) < 19 or blob[:3] not in {b"v10", b"v11"}:
        raise CursorUsageError("Cursor login uses an unrecognized sealed format")
    key = hashlib.pbkdf2_hmac(
        "sha1",
        password.encode("utf-8"),
        _LINUX_SALT,
        _LINUX_ITERATIONS,
        dklen=_LINUX_KEY_BYTES,
    )
    cipher = Cipher(algorithms.AES(key), modes.CBC(_LINUX_IV), backend=default_backend())
    decryptor = cipher.decryptor()
    try:
        padded = decryptor.update(blob[3:]) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        return unpadder.update(padded) + unpadder.finalize()
    except ValueError as error:
        raise CursorUsageError("Cursor login could not be decrypted") from error


def unseal_access_token(
    stored: str,
    *,
    lookup_password: PasswordLookup | None = None,
) -> str:
    """Return a usable access token, unsealing Electron safeStorage when needed."""
    if not is_sealed_token(stored):
        return stored

    encoded = stored[len(SEALED_PREFIX) :]
    try:
        blob = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise CursorUsageError("Cursor login uses an unrecognized sealed format") from error

    lookup = lookup_password or lookup_linux_os_crypt_password
    password = lookup()
    if not password:
        raise CursorUsageError(
            "Cursor login is sealed; unlock GNOME keyring or sign in again in Cursor Desktop"
        )

    plaintext = decrypt_linux_os_crypt(blob, password)
    try:
        token = plaintext.decode("utf-8").strip("\x00").strip()
    except UnicodeDecodeError as error:
        raise CursorUsageError("Cursor login could not be decrypted") from error
    if not token:
        raise CursorUsageError("Cursor login could not be decrypted")
    return token
