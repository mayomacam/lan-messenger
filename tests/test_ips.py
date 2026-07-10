
import os
import time
import socket
import threading
import json
import struct
from db import Database
import audit
import security_engine
from network import NetworkManager
from ssl_utils import wrap_socket

def run_ips_test():
    db_name = "test_ips.db"
    key_file = ".test_ips.key"
    if os.path.exists(db_name): os.remove(db_name)
    if os.path.exists(key_file): os.remove(key_file)

    db = Database("test_password", db_name=db_name, key_file=key_file)
    audit.init_logger(db)
    security_engine.init_engine(db)

    port = 12500
    # Initialize network manager with a token to force auth failures
    net_mgr = NetworkManager(db, port, auth_token="correct_token")

    peer_ip = "192.168.1.100" # Use non-localhost IP to bypass localhost check

    print("--- Simulating Security Incidents ---")
    for i in range(5):
        print(f"Attempt {i+1}...")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2) as raw:
                s = wrap_socket(raw)
                # Send wrong token
                packet = json.dumps({'type': 'HELLO', 'username': 'attacker', 'token': 'wrong_token'}).encode()
                length = len(packet)
                s.sendall(struct.pack('>I', length) + packet)
                resp = s.recv(1024)
                print(f"Server response: {resp}")
        except Exception as e:
            print(f"Connection error: {e}")
        time.sleep(0.5)

    print("--- Verifying Block Status ---")
    # In the test we actually connected from 127.0.0.1
    test_ip = "127.0.0.1"
    perms = db.get_peer_permissions(test_ip)
    print(f"Permissions for {test_ip}: {perms}")

    if perms.get('is_blocked'):
        print("SUCCESS: IP was automatically blocked.")
    else:
        print("FAILURE: IP was NOT blocked.")

    # Test Unblock
    print("--- Testing Unblock ---")
    db.unblock_peer(test_ip)
    perms = db.get_peer_permissions(test_ip)
    if not perms.get('is_blocked'):
        print("SUCCESS: IP was manually unblocked.")
    else:
        print("FAILURE: IP is still blocked.")

    net_mgr.close()
    db.close()
    if os.path.exists(db_name): os.remove(db_name)
    if os.path.exists(key_file): os.remove(key_file)

if __name__ == "__main__":
    run_ips_test()
