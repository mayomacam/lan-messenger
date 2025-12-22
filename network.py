import socket
import threading
import json
import time
from constants import UDP_BROADCAST_PORT, TCP_CHAT_PORT, BROADCAST_IP, BUFFER_SIZE

class PeerDiscovery:
    def __init__(self, username, broadcast_port, broadcast_ip='<broadcast>'):
        self.username = username
        self.broadcast_port = broadcast_port
        self.broadcast_ip = broadcast_ip
        self.peers = {} # ip -> username
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(('', self.broadcast_port))
        
        threading.Thread(target=self.broadcast_loop, daemon=True).start()
        threading.Thread(target=self.listen_loop, daemon=True).start()

    def broadcast_loop(self):
        while self.running:
            msg = f"IAM:{self.username}"
            try:
                self.sock.sendto(msg.encode(), (self.broadcast_ip, self.broadcast_port))
            except Exception as e:
                pass
            time.sleep(5)

    def listen_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
                msg = data.decode()
                if msg.startswith("IAM:"):
                    username = msg.split(":", 1)[1]
                    if addr[0] not in self.peers:
                        self.peers[addr[0]] = username
                        # print(f"Discovered {username} at {addr[0]}")
            except:
                pass

    def get_peers(self):
        return self.peers
    
    def stop(self):
        self.running = False
        self.sock.close()

class NetworkManager:
    def __init__(self, db, port, callback_update_ui=None):
        self.db = db
        self.port = port
        self.callback = callback_update_ui
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.bind(('0.0.0.0', self.port))
        self.server_sock.listen(10)
        self.running = True
        threading.Thread(target=self.start_server, daemon=True).start()

    def start_server(self):
        while self.running:
            try:
                client, addr = self.server_sock.accept()
                threading.Thread(target=self.handle_client, args=(client, addr), daemon=True).start()
            except:
                pass

    def handle_client(self, client, addr):
        try:
            data = client.recv(4096).decode()
            if not data: return
            
            # Protocol: TYPE|ARGS...
            parts = data.split('|')
            msg_type = parts[0]
            
            if msg_type == 'HELLO':
                # HELLO|sender_username
                sender_username = parts[1]
                # Notify UI to add peer
                if self.callback: self.callback('NEW_PEER', addr[0], sender_username)
                
                # Auto-reply with own username if it's a new connection initiating hello
                # But to avoid loops, maybe only reply if we haven't handshaked?
                # For simplicity, let's just assume the UI handles the logic of "If I receive hello, I know this peer exists".
                # The sender needs to know MY username too.
                # So if this was a HELLO, I should send back a HELLO if I initiate?
                # Let's rely on the UI to send a HELLO back if it's a new peer, or simpler:
                # The protocol should be:
                # A -> B: HELLO|UserA
                # B -> A: HELLO|UserB
                # Just handled by application logic? Or generic auto-reply?
                # Let's just notify UI. UI can check if it knows this peer.
            
            elif msg_type == 'MSG':
                # MSG|sender|content|id
                sender = parts[1]
                content = parts[2]
                msg_id = parts[3]
                timestamp = time.time()
                self.db.cursor.execute("INSERT OR IGNORE INTO messages (id, sender, content, timestamp) VALUES (?, ?, ?, ?)",
                                          (msg_id, sender, content, timestamp))
                self.db.conn.commit()
                if self.callback: self.callback('MSG', msg_id, sender, content)
            
            elif msg_type == 'MSG_EDIT':
                # MSG_EDIT|id|new_content
                msg_id = parts[1]
                new_content = parts[2]
                self.db.edit_message(msg_id, new_content)
                if self.callback: self.callback('EDIT', msg_id, new_content)

            elif msg_type == 'MSG_DEL':
                # MSG_DEL|id
                msg_id = parts[1]
                self.db.delete_message(msg_id)
                if self.callback: self.callback('DELETE', msg_id)

        except Exception as e:
            print(f"Error handling chat client: {e}")
        finally:
            client.close()

    def send_hello(self, target_ip, my_username):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2) # Short timeout for connection check
                s.connect((target_ip, self.port))
                msg = f"HELLO|{my_username}"
                s.send(msg.encode())
                return True
        except Exception as e:
            print(f"Failed to handshake with {target_ip}: {e}")
            return False

    def send_message(self, target_ip, sender_name, content, msg_id):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((target_ip, self.port))
                msg = f"MSG|{sender_name}|{content}|{msg_id}"
                s.send(msg.encode())
        except Exception as e:
            print(f"Failed to send to {target_ip}: {e}")

    def send_edit(self, target_ip, msg_id, new_content):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((target_ip, self.port))
                msg = f"MSG_EDIT|{msg_id}|{new_content}"
                s.send(msg.encode())
        except:
             pass

    def send_delete(self, target_ip, msg_id):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((target_ip, self.port))
                msg = f"MSG_DEL|{msg_id}"
                s.send(msg.encode())
        except:
            pass

    def close(self):
        self.running = False
        self.server_sock.close()
