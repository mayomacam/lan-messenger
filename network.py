import socket
import threading
import json
import time

class NetworkManager:
    def __init__(self, db, port, callback_update_ui=None):
        self.db = db
        self.port = port
        self.callback = callback_update_ui
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
                print(f"[DEBUG] Accepted connection from {addr}")
                threading.Thread(target=self.handle_client, args=(client, addr), daemon=True).start()
            except OSError as e:
                if self.running:
                     print(f"[DEBUG] Server accept error: {e}")
                else:
                     break
            except Exception as e:
                print(f"[DEBUG] Server accept error: {e}")

    def handle_client(self, client, addr):
        try:
            client.settimeout(10)
            data_raw = client.recv(8192).decode()
            if not data_raw: 
                return
            
            print(f"[DEBUG] Received data from {addr}: {data_raw}")
            try:
                data = json.loads(data_raw)
            except json.JSONDecodeError:
                print(f"[DEBUG] Failed to decode JSON from {addr}")
                return

            msg_type = data.get('type')
            
            if msg_type == 'HELLO':
                sender_username = data.get('username')
                if self.callback: self.callback('NEW_PEER', addr[0], sender_username)
            
            elif msg_type == 'MSG':
                sender = data.get('sender')
                content = data.get('content')
                msg_id = data.get('id')
                timestamp = time.time()
                self.db.add_received_message(msg_id, sender, content, timestamp)
                if self.callback: self.callback('MSG', msg_id, sender, content)
            
            elif msg_type == 'MSG_EDIT':
                msg_id = data.get('id')
                new_content = data.get('content')
                self.db.edit_message(msg_id, new_content)
                if self.callback: self.callback('EDIT', msg_id, new_content)

            elif msg_type == 'MSG_DEL':
                msg_id = data.get('id')
                self.db.delete_message(msg_id)
                if self.callback: self.callback('DELETE', msg_id)

        except Exception as e:
            print(f"[DEBUG] Error handling chat client: {e}")
        finally:
            client.close()

    def _send_packet(self, target_ip, packet):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((target_ip, self.port))
                s.sendall(json.dumps(packet).encode())
                return True
        except Exception as e:
            print(f"[DEBUG] Failed to send to {target_ip}: {e}")
            return False

    def send_hello(self, target_ip, my_username):
        return self._send_packet(target_ip, {'type': 'HELLO', 'username': my_username})

    def send_message(self, target_ip, sender_name, content, msg_id):
        self._send_packet(target_ip, {
            'type': 'MSG',
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
