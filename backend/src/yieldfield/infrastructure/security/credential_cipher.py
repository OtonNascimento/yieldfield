"""Credential encryption at rest (§11). A cipher *port* with a Fernet default.

Connector secrets are encrypted before they touch the OLTP store and decrypted only at
connector construction. The Protocol is the boundary, so the implementation can become
envelope/KMS-backed later without touching domain or application code (§17). Errors never
include the plaintext secret.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from cryptography.fernet import Fernet, InvalidToken


class CredentialCipherError(Exception):
    """Encryption/decryption failed. Never includes the plaintext secret (§11)."""


@runtime_checkable
class CredentialCipher(Protocol):
    """Encrypt/decrypt an opaque secrets mapping."""

    def encrypt(self, secrets: Mapping[str, str]) -> bytes: ...
    def decrypt(self, blob: bytes) -> Mapping[str, str]: ...


class FernetCredentialCipher:
    """Symmetric (Fernet/AES) cipher; key comes from config (§16) and is never logged."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key)
        except (ValueError, TypeError) as exc:
            raise CredentialCipherError("Invalid Fernet key for the credential cipher.") from exc

    def encrypt(self, secrets: Mapping[str, str]) -> bytes:
        payload = json.dumps(dict(secrets), sort_keys=True).encode("utf-8")
        return self._fernet.encrypt(payload)

    def decrypt(self, blob: bytes) -> Mapping[str, str]:
        try:
            payload = self._fernet.decrypt(blob)
        except InvalidToken as exc:
            raise CredentialCipherError("Could not decrypt connector credentials.") from exc
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            raise CredentialCipherError("Decrypted credentials are not a mapping.")
        return {str(k): str(v) for k, v in data.items()}
