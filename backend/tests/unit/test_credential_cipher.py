"""FernetCredentialCipher round-trips secrets and fails loudly on bad input (§11)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from yieldfield.infrastructure.security.credential_cipher import (
    CredentialCipherError,
    FernetCredentialCipher,
)


def test_encrypt_decrypt_round_trip() -> None:
    cipher = FernetCredentialCipher(Fernet.generate_key().decode())
    secrets = {"api_key": "sk_test_123", "webhook_secret": "whsec_abc"}
    blob = cipher.encrypt(secrets)
    assert isinstance(blob, bytes)
    assert b"sk_test_123" not in blob  # ciphertext, not plaintext
    assert cipher.decrypt(blob) == secrets


def test_decrypt_with_wrong_key_raises() -> None:
    blob = FernetCredentialCipher(Fernet.generate_key().decode()).encrypt({"api_key": "x"})
    other = FernetCredentialCipher(Fernet.generate_key().decode())
    with pytest.raises(CredentialCipherError):
        other.decrypt(blob)


def test_invalid_key_raises() -> None:
    with pytest.raises(CredentialCipherError):
        FernetCredentialCipher("not-a-valid-fernet-key")
