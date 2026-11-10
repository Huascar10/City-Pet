import os
import hmac
import hashlib
import secrets
import base64
from flask import current_app

class CryptoService:
    """
    Authenticated symmetric encryption service (PBKDF2-HMAC-SHA256 + CTR-HMAC-SHA256 + HMAC-SHA256 tag)
    using an external key from environment / config (never stored in the database).
    """
    PREFIX = "ENCv1:"

    @staticmethod
    def _get_master_key() -> bytes:
        env_key = os.environ.get('CITYPET_ENCRYPTION_KEY') or os.environ.get('SECRET_KEY')
        if not env_key:
            try:
                env_key = current_app.config.get('SECRET_KEY')
            except Exception:
                env_key = 'citypet-super-secret-key-production-change-me-2026'
        return str(env_key).encode('utf-8')

    @classmethod
    def _keystream(cls, enc_key: bytes, length: int) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < length:
            block = hmac.new(enc_key, counter.to_bytes(8, 'big'), hashlib.sha256).digest()
            out.extend(block)
            counter += 1
        return bytes(out[:length])

    @classmethod
    def is_encrypted(cls, value: str) -> bool:
        return bool(value and isinstance(value, str) and value.startswith(cls.PREFIX))

    @classmethod
    def encrypt_secret(cls, plaintext: str) -> str:
        if not plaintext:
            return ''
        if cls.is_encrypted(plaintext):
            return plaintext

        raw_bytes = plaintext.encode('utf-8')
        salt = secrets.token_bytes(16)
        master_key = cls._get_master_key()
        derived = hashlib.pbkdf2_hmac('sha256', master_key, salt, 100_000, dklen=64)
        k_enc, k_mac = derived[:32], derived[32:]

        stream = cls._keystream(k_enc, len(raw_bytes))
        ciphertext = bytes(a ^ b for a, b in zip(raw_bytes, stream))
        mac = hmac.new(k_mac, salt + ciphertext, hashlib.sha256).digest()

        payload = base64.urlsafe_b64encode(salt + mac + ciphertext).decode('ascii')
        return f"{cls.PREFIX}{payload}"

    @classmethod
    def decrypt_secret(cls, stored_value: str) -> str:
        if not stored_value:
            return ''
        if not cls.is_encrypted(stored_value):
            return stored_value

        b64_part = stored_value[len(cls.PREFIX):]
        raw = base64.urlsafe_b64decode(b64_part.encode('ascii'))
        if len(raw) < 48:
            raise ValueError("Token cifrado corrupto o inválido.")

        salt = raw[:16]
        mac_stored = raw[16:48]
        ciphertext = raw[48:]

        master_key = cls._get_master_key()
        derived = hashlib.pbkdf2_hmac('sha256', master_key, salt, 100_000, dklen=64)
        k_enc, k_mac = derived[:32], derived[32:]

        mac_calc = hmac.new(k_mac, salt + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(mac_stored, mac_calc):
            raise ValueError("Fallo de verificación de integridad criptográfica del token.")

        stream = cls._keystream(k_enc, len(ciphertext))
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream))
        return plaintext.decode('utf-8')
