import socket
import threading
import json
import time
import struct
import hashlib
import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from ssl_utils import wrap_socket
from constants import UDP_BROADCAST_PORT, BROADCAST_IP
import audit

class DiscoveryManager:
    def __init__(self, username, chat_port, callback_new_peer, auth_token=None):
        self.username = username
        self.chat_port = chat_port
        self.callback = callback_new_peer
        self.auth_token = auth_token
        self.udp_port = UDP_BROADCAST_PORT
        self.running = True

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except AttributeError:
            pass # SO_REUSEADDR might not be available on all platforms for UDP

        # We need another socket for listening because we can't easily bind the same socket we use for broadcasting in some OSs
        self.listen_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        threading.Thread(target=self.listen, daemon=True).start()
        threading.Thread(target=self.broadcast_loop, daemon=True).start()

    def _get_discovery_hash(self):
        if not self.auth_token:
            return None
        # Simple hash to verify peers share the same secret without sending the secret itself
        return hashlib.sha256(self.auth_token.encode()).hexdigest()

    def broadcast_loop(self):
        while self.running:
            try:
                packet = {
                    'type': 'DISCOVERY',
                    'username': self.username,
                    'port': self.chat_port
                }
                h = self._get_discovery_hash()
                if h:
                    packet['hash'] = h

                data = json.dumps(packet)
                self.sock.sendto(data.encode(), (BROADCAST_IP, self.udp_port))
            except Exception as e:
                print(f"[DEBUG] Discovery broadcast error: {e}")
            time.sleep(5)

    def listen(self):
        try:
            self.listen_sock.bind(('', self.udp_port))
        except Exception as e:
            print(f"[DEBUG] Discovery listen bind error: {e}")
            return

        while self.running:
            try:
                data, addr = self.listen_sock.recvfrom(4096)
                if not data:
                    continue
                packet = json.loads(data.decode())
                if not isinstance(packet, dict):
                    continue
                if packet.get('type') == 'DISCOVERY':
                    peer_ip = addr[0]
                    peer_username = packet.get('username')
                    if not isinstance(peer_username, str):
                        continue

                    # Security: verify hash if auth_token is set
                    my_hash = self._get_discovery_hash()
                    peer_hash = packet.get('hash')
                    if my_hash != peer_hash:
                        # Silently ignore peers that don't match our security context
                        continue

                    # Avoid discovering self by checking username
                    if peer_username != self.username:
                         if self.callback:
                             self.callback(peer_ip, peer_username)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue # Ignore malformed packets
            except Exception as e:
                if self.running:
                    print(f"[DEBUG] Discovery listen error: {e}")
                    time.sleep(1) # Brief pause before retry
                else:
                    break

    def stop(self):
        self.running = False
        try:
            self.sock.close()
            self.listen_sock.close()
        except:
            pass

class NetworkManager:
    def __init__(self, db, port, callback_update_ui=None, auth_token=None, allowed_ips=None):
        self.db = db
        self.port = port
        self.callback = callback_update_ui
        self.auth_token = auth_token
        self.allowed_ips = allowed_ips
        self.transit_cipher = None
        if self.auth_token:
            # Derive a transit key from the auth token
            # In a real enterprise app, we'd use PBKDF2/Argon2,
            # but for this P2P tool, we'll use a SHA256 of the token.
            key = hashlib.sha256(self.auth_token.encode()).digest()
            self.transit_cipher = AESGCM(key)

        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.running = True
        threading.Thread(target=self.start_server, daemon=True).start()

    def start_server(self):
        print(f"[DEBUG] Network Server starting...")
        try:
            self.server_sock.bind(('0.0.0.0', self.port))
            self.server_sock.listen(10)
            print(f"[DEBUG] Network Server LISTENING on 0.0.0.0:{self.port}")
        except Exception as e:
            print(f"[DEBUG] FAILED to bind port {self.port}: {e}")
            return

        while self.running:
            try:
                client, addr = self.server_sock.accept()
                # Wrap with TLS
                client = wrap_socket(client, server_side=True)
                threading.Thread(target=self.handle_client, args=(client, addr), daemon=True).start()
            except OSError as e:
                if self.running:
                     print(f"[DEBUG] Server accept error: {e}")
                else:
                     break
            except Exception as e:
                print(f"[DEBUG] Server accept error: {e}")

    def _recv_all(self, sock, n):
        """Helper to receive exactly n bytes."""
        data = b''
        while len(data) < n:
            packet = sock.recv(n - len(data))
            if not packet:
                return None
            data += packet
        return data

    def _recv_json(self, sock):
        """Receives a length-prefixed JSON packet (optionally encrypted)."""
        raw_msglen = self._recv_all(sock, 4)
        if not raw_msglen:
            return None
        msglen = struct.unpack('>I', raw_msglen)[0]
        if msglen > 1024 * 1024:
            return None
        raw_data = self._recv_all(sock, msglen)
        if not raw_data:
            return None

        try:
            if self.transit_cipher:
                # Decrypt transit data
                decoded = base64.b64decode(raw_data)
                nonce = decoded[:12]
                ciphertext = decoded[12:]
                decrypted = self.transit_cipher.decrypt(nonce, ciphertext, None)
                return json.loads(decrypted.decode())
            else:
                return json.loads(raw_data.decode())
        except Exception as e:
            print(f"[DEBUG] Transit decryption error: {e}")
            return None

    def _send_json(self, sock, data):
        """Sends a length-prefixed JSON packet (optionally encrypted)."""
        serialized = json.dumps(data).encode()
        if self.transit_cipher:
            nonce = os.urandom(12)
            ciphertext = self.transit_cipher.encrypt(nonce, serialized, None)
            serialized = base64.b64encode(nonce + ciphertext)

        sock.sendall(struct.pack('>I', len(serialized)) + serialized)

    def handle_client(self, client, addr):
        """Process incoming client packets with optional IP whitelist and token verification."""
        logger = audit.get_logger()
        try:
            client.settimeout(10)
            # IP whitelist enforcement
            if self.allowed_ips is not None and addr[0] not in self.allowed_ips:
                msg = f"Connection from {addr[0]} rejected: IP not allowed."
                print(f"[DEBUG] {msg}")
                if logger: logger.log("SECURITY_ALERT", msg)
                self._send_json(client, {'status': 'ERR', 'msg': 'IP not allowed'})
                return

            data = self._recv_json(client)
            if not data:
                return

            if not isinstance(data, dict):
                if logger: logger.log("SECURITY_ALERT", f"Malformed packet from {addr[0]}: Not a JSON object.")
                return

            print(f"[DEBUG] Received data from {addr}: {data}")

            # Token verification
            if self.auth_token is not None:
                if data.get('token') != self.auth_token:
                    msg = f"Connection from {addr[0]} rejected: Authentication failed."
                    print(f"[DEBUG] {msg}")
                    if logger: logger.log("AUTH_FAILURE", msg)
                    self._send_json(client, {'status': 'ERR', 'msg': 'Authentication failed'})
                    return

            # Existing message handling with validation
            msg_type = data.get('type')
            if not isinstance(msg_type, str):
                return

            if msg_type == 'HELLO':
                sender_username = data.get('username')
                if not isinstance(sender_username, str): return
                if logger: logger.log("CONNECTION", f"Peer {sender_username} ({addr[0]}) connected.")
                if self.callback: self.callback('NEW_PEER', addr[0], sender_username)

            elif msg_type == 'MSG':
                sender = data.get('sender')
                content = data.get('content')
                msg_id = data.get('id')
                if not all(isinstance(x, str) for x in [sender, content, msg_id]):
                    return
                timestamp = time.time()
                self.db.add_received_message(msg_id, sender, content, timestamp)
                if self.callback: self.callback('MSG', msg_id, sender, content)

            elif msg_type == 'MSG_PRIV':
                sender = data.get('sender')
                content = data.get('content')
                msg_id = data.get('id')
                if not all(isinstance(x, str) for x in [sender, content, msg_id]):
                    return
                timestamp = time.time()
                # Store with recipient = sender's IP so we can filter by peer_ip later
                self.db.add_received_message(msg_id, sender, content, timestamp, recipient=addr[0])
                if self.callback: self.callback('MSG_PRIV', msg_id, sender, content, addr[0])

            elif msg_type == 'MSG_EDIT':
                msg_id = data.get('id')
                new_content = data.get('content')
                if not all(isinstance(x, str) for x in [msg_id, new_content]):
                    return
                self.db.edit_message(msg_id, new_content)
                if self.callback: self.callback('EDIT', msg_id, new_content)

            elif msg_type == 'MSG_DEL':
                msg_id = data.get('id')
                if not isinstance(msg_id, str): return
                self.db.delete_message(msg_id)
                if self.callback: self.callback('DELETE', msg_id)

            # Additional packet types can be added here

        except Exception as e:
            print(f"[DEBUG] Error handling chat client: {e}")
        finally:
            client.close()

    def _send_packet(self, target_ip, packet):
        """Send a JSON packet to target_ip, attaching auth token if configured."""
        try:
            if self.auth_token is not None:
                packet['token'] = self.auth_token
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
                raw.settimeout(5)
                raw.connect((target_ip, self.port))
                s = wrap_socket(raw)
                self._send_json(s, packet)
                return True
        except Exception as e:
            print(f"[DEBUG] Failed to send to {target_ip}: {e}")
            return False

    def send_hello(self, target_ip, my_username):
        return self._send_packet(target_ip, {'type': 'HELLO', 'username': my_username})

    def send_message(self, target_ip, sender_name, content, msg_id, is_private=False):
        msg_type = 'MSG_PRIV' if is_private else 'MSG'
        self._send_packet(target_ip, {
            'type': msg_type,
            'sender': sender_name,
            'content': content,
            'id': msg_id
        })

    def send_edit(self, target_ip, msg_id, new_content):
        self._send_packet(target_ip, {
            'type': 'MSG_EDIT',
            'id': msg_id,
            'content': new_content
        })

    def send_delete(self, target_ip, msg_id):
        self._send_packet(target_ip, {
            'type': 'MSG_DEL',
            'id': msg_id
        })

    def close(self):
        self.running = False
        try:
            self.server_sock.close()
        except:
            pass
