import socket
import threading
import os
import json
import time

class FileTransferManager:
    def __init__(self, db, port, save_dir="downloads"):
        self.db = db
        self.port = port
        self.save_dir = save_dir
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind(('0.0.0.0', self.port))
            self.server_socket.listen(5)
            self.running = True
            threading.Thread(target=self.start_server, daemon=True).start()
        except Exception as e:
            print(f"[DEBUG] File server failed to start: {e}")
            self.running = False

    def start_server(self):
        while self.running:
            try:
                client, addr = self.server_socket.accept()
                threading.Thread(target=self.handle_client, args=(client,), daemon=True).start()
            except Exception as e:
                if self.running:
                    print(f"[DEBUG] File server accept error: {e}")
                break

    def handle_client(self, client):
        try:
            client.settimeout(10)
            header_raw = client.recv(4096).decode()
            if not header_raw: return
            
            try:
                req = json.loads(header_raw)
            except json.JSONDecodeError:
                print(f"[DEBUG] File server received invalid JSON header")
                return

            cmd = req.get('cmd')
            
            if cmd == 'PUSH_FILE':
                filename = req.get('filename')
                size = req.get('size')
                client.sendall(b'ACK')
                self.receive_stream(client, filename, size)
            
            elif cmd == 'PULL_FILE':
                path = req.get('path')
                if os.path.exists(path) and os.path.isfile(path):
                    size = os.path.getsize(path)
                    client.sendall(json.dumps({'status': 'OK', 'size': size}).encode())
                    ack = client.recv(1024)
                    with open(path, 'rb') as f:
                        while True:
                            data = f.read(8192)
                            if not data: break
                            client.sendall(data)
                else:
                    client.sendall(json.dumps({'status': 'ERR', 'msg': 'File not found'}).encode())
            
            elif cmd == 'LIST_SHARED':
                files = self.db.get_files()
                file_list = []
                for f in files:
                    file_list.append({
                        'filename': f[1],
                        'path': f[2],
                        'size': f[3],
                        'is_folder': f[5],
                        'owner': f[4]
                    })
                data = json.dumps(file_list)
                client.sendall(json.dumps({'status': 'OK', 'size': len(data)}).encode())
                ack = client.recv(1024)
                client.sendall(data.encode())
            
            elif cmd == 'LIST_FOLDER':
                path = req.get('path')
                if os.path.exists(path) and os.path.isdir(path):
                    files = []
                    for r, d, files_in_dir in os.walk(path):
                        for file in files_in_dir:
                            full_path = os.path.join(r, file)
                            rel_path = os.path.relpath(full_path, path)
                            files.append({'rel_path': rel_path, 'size': os.path.getsize(full_path)})
                    data = json.dumps(files)
                    client.sendall(json.dumps({'status': 'OK', 'size': len(data)}).encode())
                    ack = client.recv(1024)
                    client.sendall(data.encode())
                else:
                    client.sendall(json.dumps({'status': 'ERR', 'msg': 'Folder not found'}).encode())
                    
        except Exception as e:
            print(f"[DEBUG] Error handling file client: {e}")
        finally:
            client.close()

    def receive_stream(self, sock, filename, size, subfolder=""):
        final_dir = os.path.join(self.save_dir, subfolder)
        if not os.path.exists(final_dir):
            os.makedirs(final_dir)
            
        path = os.path.join(final_dir, filename)
        received = 0
        with open(path, 'wb') as f:
            while received < size:
                data = sock.recv(min(8192, size - received))
                if not data: break
                f.write(data)
                received += len(data)
        print(f"[DEBUG] Received {filename}")

    def download_file(self, target_ip, remote_path):
        filename = os.path.basename(remote_path)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10)
                s.connect((target_ip, self.port))
                s.sendall(json.dumps({'cmd': 'PULL_FILE', 'path': remote_path}).encode())
                resp_raw = s.recv(4096).decode()
                resp = json.loads(resp_raw)
                if resp.get('status') == 'OK':
                    size = resp.get('size')
                    s.sendall(b'ACK')
                    self.receive_stream(s, filename, size)
                else:
                    print(f"[DEBUG] Download failed: {resp.get('msg')}")
        except Exception as e:
            print(f"[DEBUG] Download error: {e}")

    def download_folder(self, target_ip, remote_path):
        folder_name = os.path.basename(remote_path)
        try:
            file_list = []
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10)
                s.connect((target_ip, self.port))
                s.sendall(json.dumps({'cmd': 'LIST_FOLDER', 'path': remote_path}).encode())
                resp_raw = s.recv(4096).decode()
                resp = json.loads(resp_raw)
                if resp.get('status') == 'OK':
                    size = resp.get('size')
                    s.sendall(b'ACK')
                    data = b""
                    while len(data) < size:
                        chunk = s.recv(8192)
                        if not chunk: break
                        data += chunk
                    file_list = json.loads(data)
                else:
                    print(f"[DEBUG] Folder list failed: {resp.get('msg')}")
                    return

            for item in file_list:
                rel_path = item['rel_path']
                full_remote_path = os.path.join(remote_path, rel_path)
                self._download_file_direct(target_ip, full_remote_path, folder_name, rel_path)
                
        except Exception as e:
            print(f"[DEBUG] Folder download error: {e}")

    def _download_file_direct(self, target_ip, remote_path, folder_name, rel_path):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(10)
                s.connect((target_ip, self.port))
                s.sendall(json.dumps({'cmd': 'PULL_FILE', 'path': remote_path}).encode())
                resp_raw = s.recv(4096).decode()
                resp = json.loads(resp_raw)
                if resp.get('status') == 'OK':
                    size = resp.get('size')
                    s.sendall(b'ACK')
                    local_file_path = os.path.join(self.save_dir, folder_name, rel_path)
                    local_folder = os.path.dirname(local_file_path)
                    if not os.path.exists(local_folder):
                        os.makedirs(local_folder)
                    received = 0
                    with open(local_file_path, 'wb') as f:
                        while received < size:
                            chunk = s.recv(min(8192, size - received))
                            if not chunk: break
                            f.write(chunk)
                            received += len(chunk)
                    print(f"[DEBUG] Downloaded {rel_path}")
        except Exception as e:
             print(f"[DEBUG] File {rel_path} download error: {e}")

    def get_shared_files(self, target_ip):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect((target_ip, self.port))
                s.sendall(json.dumps({'cmd': 'LIST_SHARED'}).encode())
                resp_raw = s.recv(4096).decode()
                resp = json.loads(resp_raw)
                if resp.get('status') == 'OK':
                    size = resp.get('size')
                    s.sendall(b'ACK')
                    data = b""
                    while len(data) < size:
                        chunk = s.recv(8192)
                        if not chunk: break
                        data += chunk
                    return json.loads(data)
        except Exception as e:
            print(f"[DEBUG] Get shared files error: {e}")
        return []

    def close(self):
        self.running = False
        try:
            self.server_socket.close()
        except:
            pass
