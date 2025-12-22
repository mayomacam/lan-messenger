import socket
import threading
import json
import time
from constants import UDP_BROADCAST_PORT, TCP_CHAT_PORT, BROADCAST_IP, BUFFER_SIZE

class NetworkManager:
    def __init__(self, db, port, callback_update_ui=None):
        self.db = db
        self.port = port
        self.callback = callback_update_ui
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # self.server_sock.bind removed from here, moved to start_server
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
                print(f"[DEBUG] Accepted connection from {addr}")
                threading.Thread(target=self.handle_client, args=(client, addr), daemon=True).start()
            except OSError as e:
                if self.running:
                     print(f"[DEBUG] Server accept error: {e}")
                else:
                     # Socket closed, expected
                     break
            except Exception as e:
                print(f"[DEBUG] Server accept error: {e}")

    def handle_client(self, client, addr):
        try:
            print(f"[DEBUG] Handling client {addr}")
            data = client.recv(4096).decode()
            if not data: 
                print(f"[DEBUG] No data received from {addr}")
                return
            
            print(f"[DEBUG] Received data from {addr}: {data}")
            # Protocol: TYPE|ARGS...
            parts = data.split('|')
            msg_type = parts[0]
            
            if msg_type == 'HELLO':
                # HELLO|sender_username
                sender_username = parts[1]
                print(f"[DEBUG] Processing HELLO from {sender_username} at {addr[0]}")
                # Notify UI to add peer
                if self.callback: self.callback('NEW_PEER', addr[0], sender_username)
            
            elif msg_type == 'MSG':
                # MSG|sender|content|id
                sender = parts[1]
                content = parts[2]
                msg_id = parts[3]
                print(f"[DEBUG] Processing MSG from {sender}: {content}")
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
            print(f"[DEBUG] Error handling chat client: {e}")
        finally:
            client.close()

    def send_hello(self, target_ip, my_username):
        print(f"[DEBUG] Attempting to send HELLO to {target_ip}:{self.port}")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5) # Increased timeout
                s.connect((target_ip, self.port))
                msg = f"HELLO|{my_username}"
                s.send(msg.encode())
                print(f"[DEBUG] HELLO sent to {target_ip}")
                return True
        except Exception as e:
            print(f"[DEBUG] Failed to handshake with {target_ip}: {e}")
            return False

    def send_message(self, target_ip, sender_name, content, msg_id):
        print(f"[DEBUG] Sending MSG to {target_ip}")
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((target_ip, self.port))
                msg = f"MSG|{sender_name}|{content}|{msg_id}"
                s.send(msg.encode())
        except Exception as e:
            print(f"[DEBUG] Failed to send to {target_ip}: {e}")

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
