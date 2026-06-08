"""Small server-side encryption helper for local config secrets."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

TOKEN_PREFIX = "enc:v1:"
_SALT_BYTES = 16
_NONCE_BYTES = 16


class ConfigCryptoError(RuntimeError):
    """Raised when a config secret cannot be encrypted or decrypted."""


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def is_encrypted_token(value: str | None) -> bool:
    return bool(value and value.startswith(TOKEN_PREFIX))


def _require_secret(secret: str | None) -> bytes:
    normalized = (secret or "").strip()
    if not normalized:
        raise ConfigCryptoError("CONFIG_ENCRYPTION_KEY or APP_SECRET_KEY must be configured")
    return normalized.encode("utf-8")


def _derive_keys(secret: str, salt: bytes) -> tuple[bytes, bytes]:
    root = hashlib.pbkdf2_hmac("sha256", _require_secret(secret), salt, 200_000, dklen=64)
    return root[:32], root[32:]


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks = []
    counter = 0
    while sum(len(block) for block in blocks) < length:
        blocks.append(hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(blocks)[:length]


def encrypt_config_secret(value: str, secret: str) -> str:
    plaintext = value.encode("utf-8")
    salt = os.urandom(_SALT_BYTES)
    nonce = os.urandom(_NONCE_BYTES)
    enc_key, mac_key = _derive_keys(secret, salt)
    stream = _keystream(enc_key, nonce, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
    body = {
        "alg": "PBKDF2-HMAC-SHA256+HMAC-STREAM",
        "salt": _b64e(salt),
        "nonce": _b64e(nonce),
        "ciphertext": _b64e(ciphertext),
    }
    mac_input = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body["tag"] = _b64e(hmac.new(mac_key, mac_input, hashlib.sha256).digest())
    token = _b64e(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    return f"{TOKEN_PREFIX}{token}"


def decrypt_config_secret(token: str, secret: str) -> str:
    if not is_encrypted_token(token):
        return token
    try:
        body = json.loads(_b64d(token[len(TOKEN_PREFIX):]))
        salt = _b64d(str(body["salt"]))
        nonce = _b64d(str(body["nonce"]))
        ciphertext = _b64d(str(body["ciphertext"]))
        enc_key, mac_key = _derive_keys(secret, salt)
        tag = _b64d(str(body["tag"]))
        mac_body = {k: body[k] for k in ("alg", "salt", "nonce", "ciphertext")}
        mac_input = json.dumps(mac_body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        expected = hmac.new(mac_key, mac_input, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ConfigCryptoError("Encrypted config secret authentication failed")
        stream = _keystream(enc_key, nonce, len(ciphertext))
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream))
        return plaintext.decode("utf-8")
    except ConfigCryptoError:
        raise
    except Exception as exc:
        raise ConfigCryptoError("Encrypted config secret is not readable") from exc
