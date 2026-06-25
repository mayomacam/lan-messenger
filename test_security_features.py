import unittest
import socket
import json
import time
import threading
import os
import shutil
from db import Database
from network import NetworkManager
from file_transfer import FileTransferManager
import audit
import ssl
from ssl_utils import wrap_socket

class TestSecurityFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Setup temporary database
        cls.db_name = "test_security.db"
        if os.path.exists(cls.db_name):
            os.remove(cls.db_name)
        cls.db = Database(cls.db_name)
        audit.init_logger(cls.db)

        cls.chat_port = 12357
        cls.file_port = 12356

        cls.network_mgr = NetworkManager(cls.db, cls.chat_port)
        cls.file_mgr = FileTransferManager(cls.db, cls.file_port)

        # Give servers time to start
        time.sleep(1)

    @classmethod
    def tearDownClass(cls):
        cls.network_mgr.close()
        cls.file_mgr.close()
        cls.db.close()
        if os.path.exists(cls.db_name):
            os.remove(cls.db_name)
        if os.path.exists(".master.key"):
            pass # Keep it for other tests if necessary or delete if unique

    def test_01_blocked_peer_network(self):
        """Test that a blocked peer cannot connect to the network server."""
        peer_ip = "127.0.0.1"
        self.db.update_peer_permissions(peer_ip, {'is_blocked': True})

        # Try to connect
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            try:
                s.connect(("127.0.0.1", self.chat_port))
                # The server should drop the connection immediately after accept
                # before we can even do anything.
                # In some OS/circumstances, recv might be needed to see the drop
                data = s.recv(1024)
                self.assertEqual(data, b"", "Connection should have been closed by server")
            except (ConnectionResetError, socket.timeout, BrokenPipeError):
                pass # Expected

    def test_02_unauthorized_chat(self):
        """Test that a peer without can_chat permission is rejected."""
        peer_ip = "127.0.0.1"
        self.db.add_trusted_peer(peer_ip, "Tester", "dummy-fingerprint")
        self.db.update_peer_permissions(peer_ip, {'is_blocked': False, 'can_chat': False})

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
            raw.settimeout(2)
            raw.connect(("127.0.0.1", self.chat_port))
            s = wrap_socket(raw)

            # Send a MSG packet
            packet = {
                'type': 'MSG',
                'sender': 'Attacker',
                'content': 'I should not be able to chat',
                'id': 'test-msg-1'
            }
            serialized = json.dumps(packet).encode()
            import struct
            s.sendall(struct.pack('>I', len(serialized)) + serialized)

            # Wait for response
            raw_msglen = s.recv(4)
            if raw_msglen:
                msglen = struct.unpack('>I', raw_msglen)[0]
                resp_data = s.recv(msglen)
                resp = json.loads(resp_data.decode())
                self.assertEqual(resp.get('status'), 'ERR')
                self.assertEqual(resp.get('msg'), 'Access denied')

    def test_03_unauthorized_file_list(self):
        """Test that a peer without can_list_files permission is rejected."""
        peer_ip = "127.0.0.1"
        self.db.add_trusted_peer(peer_ip, "Tester", "dummy-fingerprint")
        self.db.update_peer_permissions(peer_ip, {'is_blocked': False, 'can_list_files': False})

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
            raw.settimeout(2)
            raw.connect(("127.0.0.1", self.file_port))
            s = wrap_socket(raw)

            payload = {'cmd': 'LIST_SHARED'}
            s.sendall(json.dumps(payload).encode())

            resp_data = s.recv(4096).decode()
            resp = json.loads(resp_data)
            self.assertEqual(resp.get('status'), 'ERR')
            self.assertEqual(resp.get('msg'), 'Access denied')

    def test_04_unauthorized_file_download(self):
        """Test that a peer without can_download_files permission is rejected."""
        peer_ip = "127.0.0.1"
        self.db.add_trusted_peer(peer_ip, "Tester", "dummy-fingerprint")
        self.db.update_peer_permissions(peer_ip, {'is_blocked': False, 'can_download_files': False})

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
            raw.settimeout(2)
            raw.connect(("127.0.0.1", self.file_port))
            s = wrap_socket(raw)

            payload = {'cmd': 'PULL_FILE', 'path': '/etc/passwd'} # Path doesn't matter, perms check first
            s.sendall(json.dumps(payload).encode())

            resp_data = s.recv(4096).decode()
            resp = json.loads(resp_data)
            self.assertEqual(resp.get('status'), 'ERR')
            self.assertEqual(resp.get('msg'), 'Access denied')

if __name__ == '__main__':
    unittest.main()
