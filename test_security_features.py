
import unittest
import os
import time
from db import Database

class TestSecurityFeatures(unittest.TestCase):
    def setUp(self):
        self.db_name = "test_security.db"
        if os.path.exists(self.db_name):
            os.remove(self.db_name)
        self.db = Database(self.db_name)
        self.peer_ip = "192.168.1.100"
        self.db.add_trusted_peer(self.peer_ip, "TestPeer", "fingerprint123")

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.db_name):
            os.remove(self.db_name)

    def test_default_permissions(self):
        perms = self.db.get_peer_permissions(self.peer_ip)
        self.assertTrue(perms['can_chat'])
        self.assertTrue(perms['can_list_files'])
        self.assertTrue(perms['can_download_files'])
        self.assertFalse(perms['is_blocked'])

    def test_update_permissions(self):
        new_perms = {
            'can_chat': False,
            'can_list_files': True,
            'can_download_files': False,
            'is_blocked': True
        }
        self.db.update_peer_permissions(self.peer_ip, new_perms)
        perms = self.db.get_peer_permissions(self.peer_ip)
        self.assertEqual(perms, new_perms)
        self.assertTrue(self.db.is_peer_blocked(self.peer_ip))

    def test_file_sharing_authorization(self):
        # Share a folder
        shared_folder = "/home/user/shared"
        self.db.add_file("shared", shared_folder, 0, "127.0.0.1", is_folder=True)

        # Test exact match
        self.assertTrue(self.db.is_file_shared(shared_folder))

        # Test file inside folder
        file_inside = os.path.join(shared_folder, "test.txt")
        self.assertTrue(self.db.is_file_shared(file_inside))

        # Test file outside folder
        file_outside = "/home/user/secret.txt"
        self.assertFalse(self.db.is_file_shared(file_outside))

        # Test partial prefix that isn't a subpath
        partial = "/home/user/shared_secrets"
        self.assertFalse(self.db.is_file_shared(partial))

    def test_add_trusted_peer_preserves_permissions(self):
        new_perms = {
            'can_chat': False,
            'can_list_files': False,
            'can_download_files': False,
            'is_blocked': True
        }
        self.db.update_peer_permissions(self.peer_ip, new_perms)

        # Re-add/update peer (e.g. from HELLO packet)
        self.db.add_trusted_peer(self.peer_ip, "UpdatedName", "fingerprint123")

        perms = self.db.get_peer_permissions(self.peer_ip)
        self.assertEqual(perms, new_perms)

        peer = self.db.get_trusted_peer(self.peer_ip)
        self.assertEqual(peer[1], "UpdatedName")

if __name__ == "__main__":
    unittest.main()
