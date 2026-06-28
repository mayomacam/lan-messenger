import os
import unittest
from db import Database, EncryptionManager

class TestEncryption(unittest.TestCase):
    def setUp(self):
        self.key_file = ".test_master.key"
        self.db_name = "test_enc.db"
        if os.path.exists(self.key_file): os.remove(self.key_file)
        if os.path.exists(self.db_name): os.remove(self.db_name)

    def tearDown(self):
        if os.path.exists(self.key_file): os.remove(self.key_file)
        if os.path.exists(self.db_name): os.remove(self.db_name)

    def test_key_derivation_and_encryption(self):
        password = "secret_password"
        # First initialization creates the key
        em = EncryptionManager(password, key_file=self.key_file)
        original_text = "Sensitive information"
        encrypted_text = em.encrypt(original_text)
        self.assertTrue(encrypted_text.startswith("enc:"))

        # Second initialization with same password should decrypt
        em2 = EncryptionManager(password, key_file=self.key_file)
        decrypted_text = em2.decrypt(encrypted_text)
        self.assertEqual(original_text, decrypted_text)

    def test_invalid_password(self):
        password = "secret_password"
        em = EncryptionManager(password, key_file=self.key_file)

        with self.assertRaises(ValueError) as cm:
            EncryptionManager("wrong_password", key_file=self.key_file)
        self.assertEqual(str(cm.exception), "Invalid Master Password.")

    def test_database_with_password(self):
        password = "db_password"
        db = Database(password, db_name=self.db_name)
        msg_id = db.add_message("sender", "secret message")
        db.close()

        # Open again with correct password
        db2 = Database(password, db_name=self.db_name)
        msgs = db2.get_messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0][2], "secret message")
        db2.close()

        # Open with wrong password should fail
        with self.assertRaises(ValueError):
            Database("wrong", db_name=self.db_name)

if __name__ == "__main__":
    unittest.main()
