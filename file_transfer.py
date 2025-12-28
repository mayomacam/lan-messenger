import socket
import threading
import os
import json
import time
import ssl
from pathlib import Path

# TLS helper – wrap a raw socket with our self‑signed cert/key
def _wrap_socket(sock: socket.socket, server_side: bool = False) -> ssl.SSLSocket:
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH if server_side else ssl.Purpose.SERVER_AUTH)
    ctx.load_cert_chain(certfile=str(Path(__file__).parent / "tls_cert.pem"),
                        keyfile=str(Path(__file__).parent / "tls_key.pem"))
    if not server_side:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx.wrap_socket(sock, server_side=server_side)

class FileTransferManager:
    def __init__(self, db, port, save_dir="downloads", bind_ip="0.0.0.0", auth_token=None, allowed_ips=None):
        """Initialize the file transfer manager.
        Parameters:
            db: Database instance (can be None for now).
            port: Port number to listen on.
            save_dir: Directory where received files are saved.
            bind_ip: IP address or interface to bind the server socket to.
            auth_token: Optional shared secret token for simple authentication.
            allowed_ips: Optional list of client IPs allowed to connect.
        """
        self.db = db
        self.port = port
        self.save_dir = save_dir
        self.bind_ip = bind_ip
        self.auth_token = auth_token
        self.allowed_ips = allowed_ips
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.server_socket.bind((self.bind_ip, self.port))
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
                # Wrap the raw socket with TLS before handing to handler
                client = _wrap_socket(client, server_side=True)
                threading.Thread(target=self.handle_client, args=(client, addr), daemon=True).start()
            except Exception as e:
                if self.running:
                    print(f"[DEBUG] File server accept error: {e}")
                break

    def handle_client(self, client, addr):
        """Handle a client connection.
        Includes optional IP whitelist enforcement.
        """
        try:
            client.settimeout(10)
            # IP whitelist check
            if self.allowed_ips is not None and addr[0] not in self.allowed_ips:
                client.sendall(json.dumps({'status': 'ERR', 'msg': 'IP not allowed'}).encode())
                return

            header_raw = client.recv(4096).decode()
            if not header_raw:
                return
            
            try:
                req = json.loads(header_raw)
            except json.JSONDecodeError:
                print(f"[DEBUG] File server received invalid JSON header")
                return

            # Simple token authentication if enabled
            if self.auth_token is not None:
                if req.get('token') != self.auth_token:
                    client.sendall(json.dumps({'status': 'ERR', 'msg': 'Authentication failed'}).encode())
                    return
                # token matches – continue processing
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
                # Use pathlib for OS‑independent path handling and include directories in the listing
                from pathlib import Path
                path_str = req.get('path')
                base_path = Path(path_str)
                if base_path.exists() and base_path.is_dir():
                    entries = []
                    for entry in base_path.rglob('*'):
                        rel_path = entry.relative_to(base_path).as_posix()
                        if entry.is_file():
                            entries.append({
                                'type': 'file',
                                'rel_path': rel_path,
                                'size': entry.stat().st_size
                            })
                        elif entry.is_dir():
                            entries.append({
                                'type': 'dir',
                                'rel_path': rel_path,
                                'size': 0
                            })
                    data = json.dumps(entries)
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
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
                raw.settimeout(10)
                raw.connect((target_ip, self.port))
                s = _wrap_socket(raw)
                payload = {'cmd': 'PULL_FILE', 'path': remote_path}
                if self.auth_token is not None:
                    payload['token'] = self.auth_token
                s.sendall(json.dumps(payload).encode())
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

    def download_folder(self, target_ip, remote_path, progress_callback=None):
        """Download an entire folder with rich progress reporting.
        *progress_callback* is an optional callable that receives four arguments:
            (rel_path: str, status: str, file_ratio: float, overall_ratio: float)
        *status* can be "START", "PROGRESS", "DONE" or "ERROR".
        "file_ratio" is the per‑file progress (0‑1). "overall_ratio" is the overall folder progress (0‑1).
        """
        folder_name = os.path.basename(remote_path)
        try:
            # 1️⃣ Get folder listing
            file_list = []
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
                raw.settimeout(10)
                raw.connect((target_ip, self.port))
                s = _wrap_socket(raw)
                payload = {'cmd': 'LIST_FOLDER', 'path': remote_path}
                if self.auth_token is not None:
                    payload['token'] = self.auth_token
                s.sendall(json.dumps(payload).encode())
                resp_raw = s.recv(4096).decode()
                resp = json.loads(resp_raw)
                if resp.get('status') != 'OK':
                    print(f"[DEBUG] Folder list failed: {resp.get('msg')}")
                    return
                size = resp.get('size')
                s.sendall(b'ACK')
                data = b""
                while len(data) < size:
                    chunk = s.recv(8192)
                    if not chunk:
                        break
                    data += chunk
                file_list = json.loads(data)

            # Filter only files
            files = [f for f in file_list if f.get('type') == 'file']
            total_files = len(files)
            for idx, item in enumerate(files, start=1):
                rel_path = item['rel_path']
                full_remote_path = os.path.join(remote_path, rel_path)
                # Notify start
                if progress_callback:
                    try:
                        progress_callback(rel_path, "START", 0.0, (idx - 1) / total_files)
                    except Exception as e:
                        print(f"[DEBUG] Progress callback error (START) for {rel_path}: {e}")
                # Download with per‑file progress reporting
                success = self._download_file_direct(target_ip, full_remote_path, folder_name, rel_path,
                                                    per_file_cb=progress_callback,
                                                    overall_index=idx,
                                                    overall_total=total_files)
                # Notify end
                if progress_callback:
                    try:
                        status = "DONE" if success else "ERROR"
                        progress_callback(rel_path, status, 1.0, idx / total_files)
                    except Exception as e:
                        print(f"[DEBUG] Progress callback error (END) for {rel_path}: {e}")
        except Exception as e:
            print(f"[DEBUG] Folder download error: {e}")

    def _download_file_direct(self, target_ip, remote_path, folder_name, rel_path,
                            per_file_cb=None, overall_index=0, overall_total=1):
        """Download a single file with optional per‑file progress callback.
        Returns *True* on success, *False* on any error.
        Uses pathlib for cross‑platform path handling and includes auth token if set.
        """
        from pathlib import Path
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
                raw.settimeout(10)
                raw.connect((target_ip, self.port))
                s = _wrap_socket(raw)
                payload = {'cmd': 'PULL_FILE', 'path': remote_path}
                if self.auth_token is not None:
                    payload['token'] = self.auth_token
                s.sendall(json.dumps(payload).encode())
                resp_raw = s.recv(4096).decode()
                resp = json.loads(resp_raw)
                if resp.get('status') == 'OK':
                    size = resp.get('size')
                    s.sendall(b'ACK')
                    local_path = Path(self.save_dir) / folder_name / rel_path
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    received = 0
                    with open(local_path, 'wb') as f:
                        while received < size:
                            chunk = s.recv(min(8192, size - received))
                            if not chunk:
                                break
                            f.write(chunk)
                            received += len(chunk)
                            # per‑file progress update
                            if per_file_cb:
                                try:
                                    file_ratio = received / size if size else 0.0
                                    overall_ratio = overall_index / overall_total
                                    per_file_cb(rel_path, "PROGRESS", file_ratio, overall_ratio)
                                except Exception as e:
                                    print(f"[DEBUG] Progress callback error (PROGRESS) for {rel_path}: {e}")
                    print(f"[DEBUG] Downloaded {rel_path}")
                    return True
                else:
                    print(f"[DEBUG] File {rel_path} download error: {resp.get('msg')}")
                    return False
        except Exception as e:
            print(f"[DEBUG] File {rel_path} download error: {e}")
            return False

    def get_shared_files(self, target_ip):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
                raw.settimeout(5)
                raw.connect((target_ip, self.port))
                s = _wrap_socket(raw)
                payload = {'cmd': 'LIST_SHARED'}
                if self.auth_token is not None:
                    payload['token'] = self.auth_token
                s.sendall(json.dumps(payload).encode())
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
