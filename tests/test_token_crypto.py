from cryptography.fernet import Fernet

from app.token_crypto import decrypt, encrypt


def test_roundtrip():
    key = Fernet.generate_key().decode()
    ciphertext = encrypt(key, "a-secret-access-token")
    assert ciphertext != "a-secret-access-token"
    assert decrypt(key, ciphertext) == "a-secret-access-token"


def test_different_keys_cannot_decrypt_each_others_ciphertext():
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()
    ciphertext = encrypt(key_a, "secret")
    try:
        decrypt(key_b, ciphertext)
        assert False, "expected decryption to fail with the wrong key"
    except Exception:
        pass
