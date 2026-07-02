import os
import unittest
from db import EncryptionManager

class TestKeyEncryption(unittest.TestCase):
    def setUp(self):
        self.key_file = ".test_master.key"
        if os.path.exists(self.key_file):
            os.remove(self.key_file)

    def tearDown(self):
        if os.path.exists(self.key_file):
            os.remove(self.key_file)

    def test_encryption_decryption_cycle(self):
        password = "secure_password123"
        em = EncryptionManager(key_file=self.key_file, password=password)

        test_data = "Hello World"
        encrypted = em.encrypt(test_data)
        self.assertNotEqual(test_data, encrypted)
        self.assertTrue(encrypted.startswith("enc:"))

        # New manager instance with same password
        em2 = EncryptionManager(key_file=self.key_file, password=password)
        decrypted = em2.decrypt(encrypted)
        self.assertEqual(test_data, decrypted)

    def test_invalid_password(self):
        password = "correct_password"
        EncryptionManager(key_file=self.key_file, password=password)

        with self.assertRaises(ValueError):
            EncryptionManager(key_file=self.key_file, password="wrong_password")

    def test_migration_from_unencrypted(self):
        # Create an unencrypted 32-byte key
        old_key = os.urandom(32)
        with open(self.key_file, "wb") as f:
            f.write(old_key)

        password = "new_password"
        em = EncryptionManager(key_file=self.key_file, password=password)
        self.assertEqual(em.key, old_key)

        # Check that it's now encrypted (larger than 32 bytes)
        file_size = os.path.getsize(self.key_file)
        self.assertEqual(file_size, 76) # 16 + 12 + 32 + 16

if __name__ == '__main__':
    unittest.main()
