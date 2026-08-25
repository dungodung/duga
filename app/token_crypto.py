"""Symmetric encryption for OAuth tokens at rest (app/models/oauth_token.py).
A dedicated key (DUGA_TOKEN_ENCRYPTION_KEY), not SECRET_KEY -- different
purpose (Flask's session-cookie signing vs. encrypting a bearer credential
to a live external service), different blast radius if either one leaks.
"""
from cryptography.fernet import Fernet


def encrypt(key: str, plaintext: str) -> str:
    return Fernet(key.encode()).encrypt(plaintext.encode()).decode()


def decrypt(key: str, ciphertext: str) -> str:
    return Fernet(key.encode()).decrypt(ciphertext.encode()).decode()
