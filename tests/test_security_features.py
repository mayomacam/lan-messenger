import unittest
import os
import time
import socket
import json
import struct
from db import Database
from network import NetworkManager
from file_transfer import FileTransferManager
import audit

class TestSecurityFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db_name = "test_security_final.db"
        if os.path.exists(cls.db_name):
            os.remove(cls.db_name)
        cls.db = Database(db_name=cls.db_name)
        audit.init_logger(cls.db)

        cls.chat_port = 12480
        cls.file_port = 12481

        cls.nm = NetworkManager(cls.db, cls.chat_port)
        cls.ftm = FileTransferManager(cls.db, cls.file_port)

        cls.peer_ip = "127.0.0.1"
        cls.db.add_trusted_peer(cls.peer_ip, "MaliciousPeer", "mock_fp")

    @classmethod
    def tearDownClass(cls):
        cls.nm.close()
        cls.ftm.close()
        cls.db.close()
        if os.path.exists(cls.db_name):
            os.remove(cls.db_name)

    def _send_raw_json(self, port, data):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(("127.0.0.1", port))
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with ctx.wrap_socket(s) as ssl_sock:
                serialized = json.dumps(data).encode()
                ssl_sock.sendall(struct.pack('>I', len(serialized)) + serialized)
                try:
                    return ssl_sock.recv(4096)
                except:
                    return None

    def test_blocked_peer_chat(self):
        self.db.update_peer_permissions(self.peer_ip, {'is_blocked': 1})
        packet = {'type': 'MSG', 'sender': 'MaliciousPeer', 'content': 'Hello', 'id': '123'}
        try:
            self._send_raw_json(self.chat_port, packet)
        except:
            pass  # Pre-TLS rejection expected for blocked peer
        msgs = self.db.get_messages()
        self.assertFalse(any(m[2] == 'Hello' for m in msgs))

    def test_restricted_chat_permission(self):
        self.db.update_peer_permissions(self.peer_ip, {'is_blocked': 0, 'can_chat': 0})
        packet = {'type': 'MSG', 'sender': 'MaliciousPeer', 'content': 'Forbidden Chat', 'id': '456'}
        self._send_raw_json(self.chat_port, packet)
        msgs = self.db.get_messages()
        self.assertFalse(any(m[2] == 'Forbidden Chat' for m in msgs))

    def test_restricted_file_listing(self):
        self.db.update_peer_permissions(self.peer_ip, {'is_blocked': 0, 'can_list_files': 0})
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2)
            s.connect(("127.0.0.1", self.file_port))
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with ctx.wrap_socket(s) as ssl_sock:
                req = {'cmd': 'LIST_SHARED'}
                ssl_sock.sendall(json.dumps(req).encode())
                resp = ssl_sock.recv(4096).decode()
                resp_data = json.loads(resp)
                self.assertEqual(resp_data.get('status'), 'ERR')

if __name__ == "__main__":
    unittest.main()
