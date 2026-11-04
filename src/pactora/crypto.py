import base64
import hashlib
import hmac
import json
import secrets

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(data: str) -> bytes:
    return base64.b64decode(data, validate=True)


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def password_hash(password: str) -> str:
    if len(password) < 12:
        raise ValueError("use a password with at least 12 characters")
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2${b64(salt)}${b64(derived)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, salt, expected = encoded.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), unb64(salt), 600_000)
        return hmac.compare_digest(actual, unb64(expected))
    except (ValueError, TypeError):
        return False


class PrivateStoreCipher:
    """Independent operational-storage key. Does not use a wallet spending key."""

    def __init__(self, key: str):
        raw = unb64(key)
        if len(raw) != 32:
            raise ValueError("master key must decode to 32 bytes")
        self._cipher = AESGCM(raw)

    def encrypt(self, value, purpose: str) -> str:
        iv = secrets.token_bytes(12)
        return b64(iv + self._cipher.encrypt(iv, canonical(value), purpose.encode()))

    def decrypt(self, value: str, purpose: str):
        raw = unb64(value)
        return json.loads(self._cipher.decrypt(raw[:12], raw[12:], purpose.encode()))


def validate_device_key(pem: str):
    key = serialization.load_pem_public_key(pem.encode())
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072:
        raise ValueError("device key must be RSA-3072 or stronger")
    return key


def seal_to_device(value, pem: str) -> dict:
    key = validate_device_key(pem)
    secret, iv = secrets.token_bytes(32), secrets.token_bytes(12)
    ciphertext = AESGCM(secret).encrypt(iv, canonical(value), b"veilcart-receipt-v1")
    wrapped = key.encrypt(
        secret, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    )
    return {"v": 1, "key": b64(wrapped), "iv": b64(iv), "ciphertext": b64(ciphertext)}
