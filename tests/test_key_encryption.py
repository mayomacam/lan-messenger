
import os
import shutil
from db import EncryptionManager

def test_encryption_manager():
    test_key_file = ".test_master.key"
    if os.path.exists(test_key_file):
        os.remove(test_key_file)

    password = "SuperSecurePassword123"
    em = EncryptionManager(key_file=test_key_file)

    print("Testing needs_setup...")
    assert em.needs_setup() == True
    assert em.is_locked() == True

    print("Testing setup...")
    em.setup(password)
    assert em.needs_setup() == False
    assert em.is_locked() == False

    test_data = "Hello, secure world!"
    encrypted = em.encrypt(test_data)
    print(f"Encrypted data: {encrypted}")
    assert encrypted.startswith("enc:")

    decrypted = em.decrypt(encrypted)
    print(f"Decrypted data: {decrypted}")
    assert decrypted == test_data

    print("Testing persistence and unlocking...")
    em2 = EncryptionManager(key_file=test_key_file)
    assert em2.is_locked() == True

    print("Testing wrong password...")
    assert em2.unlock("wrong_password") == False
    assert em2.is_locked() == True

    print("Testing correct password...")
    assert em2.unlock(password) == True
    assert em2.is_locked() == False

    decrypted2 = em2.decrypt(encrypted)
    assert decrypted2 == test_data
    print("Decryption with new manager instance successful!")

    print("Testing locked state behavior...")
    em3 = EncryptionManager(key_file=test_key_file)
    try:
        em3.encrypt("some data")
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        print(f"Caught expected error: {e}")

    assert em3.decrypt(encrypted) == "[Locked]"

    if os.path.exists(test_key_file):
        os.remove(test_key_file)
    print("\nALL ENCRYPTION TESTS PASSED!")

if __name__ == "__main__":
    test_encryption_manager()
