import socket
import threading
import json
import time
import os
import ssl
from db import Database
from network import NetworkManager
from file_transfer import FileTransferManager
from ssl_utils import wrap_socket

# Mock audit logger
import audit
class MockLogger:
    def log(self, event_type, details):
        print(f"[MOCK AUDIT] {event_type}: {details}")

def run_security_tests():
    db_name = "test_security.db"
    key_file = ".test_security.key"
    if os.path.exists(db_name): os.remove(db_name)
    if os.path.exists(key_file): os.remove(key_file)

    # Use a dummy password for tests
    db = Database("test_password", db_name=db_name, key_file=key_file)
    audit.init_logger(db)

    chat_port = 12400
    file_port = 12401

    # Initialize managers
    net_mgr = NetworkManager(db, chat_port)
    file_mgr = FileTransferManager(db, file_port)

    peer_ip = "127.0.0.1"

    print("\n--- Testing Blocked Peer ---")
    db.add_trusted_peer(peer_ip, "Self", "fake_fingerprint")
    db.update_peer_permissions(peer_ip, {'is_blocked': True})

    # Try chat connection
    try:
        with socket.create_connection((peer_ip, chat_port), timeout=2) as raw:
            s = wrap_socket(raw)
            s.sendall(b'\x00\x00\x00\x02{}')
            resp = s.recv(1024)
            print(f"Chat response for blocked peer: {resp}")
            if b"Blocked" in resp or not resp:
                print("SUCCESS: Chat connection blocked.")
            else:
                print("FAILURE: Chat connection NOT blocked.")
    except Exception as e:
        print(f"Chat connection failed as expected: {e}")

    # Try file connection
    try:
        with socket.create_connection((peer_ip, file_port), timeout=2) as raw:
            s = wrap_socket(raw)
            s.sendall(json.dumps({'cmd': 'LIST_SHARED'}).encode())
            resp = s.recv(1024)
            print(f"File response for blocked peer: {resp}")
            if b"Blocked" in resp or not resp:
                print("SUCCESS: File connection blocked.")
            else:
                print("FAILURE: File connection NOT blocked.")
    except Exception as e:
        print(f"File connection failed as expected: {e}")

    print("\n--- Testing Chat Permission Denied ---")
    db.update_peer_permissions(peer_ip, {'is_blocked': False, 'can_chat': False})

    try:
        with socket.create_connection((peer_ip, chat_port), timeout=2) as raw:
            s = wrap_socket(raw)
            packet = json.dumps({'type': 'MSG', 'sender': 'Test', 'content': 'Hello', 'id': '1'}).encode()
            length = len(packet)
            import struct
            s.sendall(struct.pack('>I', length) + packet)
            time.sleep(0.5)
            cursor = db.conn.cursor()
            cursor.execute("SELECT * FROM messages WHERE id='1'")
            if cursor.fetchone():
                print("FAILURE: Message was added to DB despite no chat permission!")
            else:
                print("SUCCESS: Message was NOT added to DB.")
    except Exception as e:
        print(f"Chat error: {e}")

    print("\n--- Testing File List Permission Denied ---")
    db.update_peer_permissions(peer_ip, {'can_list_files': False})

    try:
        with socket.create_connection((peer_ip, file_port), timeout=2) as raw:
            s = wrap_socket(raw)
            s.sendall(json.dumps({'cmd': 'LIST_SHARED'}).encode())
            resp = s.recv(1024)
            print(f"File List response: {resp}")
            if b"Listing disabled" in resp: # Updated message from source
                print("SUCCESS: File list denied.")
            else:
                print("FAILURE: File list NOT denied.")
    except Exception as e:
        print(f"File error: {e}")

    net_mgr.close()
    file_mgr.close()
    db.close()
    if os.path.exists(db_name): os.remove(db_name)
    if os.path.exists(key_file): os.remove(key_file)

if __name__ == "__main__":
    run_security_tests()
