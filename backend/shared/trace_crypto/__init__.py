from os import environ
from cryptography.fernet import Fernet

_fernet = None


def _get_fernet():
    """Lazily initialized so importing this module doesn't require
    CONN_STRING_ENCRYPTION_KEY to already be set at process startup.

    Single source of truth for how retention_guard encrypts a registered
    data source's connection string at rest — copied into data_sources'
    container at build time (see its Dockerfile's
    `COPY shared/trace_crypto trace_crypto/`), same as trace_auth/trace_cors.
    Only data_sources ever imports this: it's the only service that touches
    ciphertext, so the encryption key only ever needs to exist in one
    service's environment."""
    global _fernet
    if _fernet is None:
        _fernet = Fernet(environ["CONN_STRING_ENCRYPTION_KEY"].encode())
    return _fernet


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
