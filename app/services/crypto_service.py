from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class CryptoService:
    def __init__(self, fernet_key: str):
        if not fernet_key:
            raise ValueError("FERNET_KEY is missing. Set it in environment.")
        self._fernet = Fernet(fernet_key.encode() if isinstance(
            fernet_key, str) else fernet_key)

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken:
            raise ValueError(
                "Unable to decrypt token. Check FERNET_KEY consistency.")
