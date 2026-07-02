import socket
import threading
import os
import json
import time
import hashlib
from pathlib import Path
from ssl_utils import wrap_socket, get_peer_fingerprint
import audit

class FileTransferManager:
    @staticmethod
    def calculate_sha256(filepath):
        """Calculate the SHA-256 hash of a file."""
        sha256_hash = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                # Read and update hash string value in blocks of 64K
                for byte_block in iter(lambda: f.read(65536), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception as e:
            print(f"[DEBUG] Error calculating hash for {filepath}: {e}")
            return None

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
        # Ensure audit logger is initialized for this database
        if self.db:
            audit.init_logger(self.db)
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
                client = wrap_socket(client, server_side=True)

                # TOFU: check peer fingerprint
                fingerprint = get_peer_fingerprint(client)
                if fingerprint:
                    self._check_tofu(addr[0], fingerprint)

                threading.Thread(target=self.handle_client, args=(client, addr), daemon=True).start()
            except Exception as e:
                if self.running:
                    print(f"[DEBUG] File server accept error: {e}")
                break

    def _check_tofu(self, ip, fingerprint):
        logger = audit.get_logger()
        existing = self.db.get_trusted_peer(ip)
        if existing:
            # existing: (ip, username, fingerprint, trust_level, last_seen)
            stored_username = existing[1]
            old_fingerprint = existing[2]
            if old_fingerprint != fingerprint:
                msg = f"SECURITY ALERT: Certificate fingerprint mismatch for {ip} during file transfer!"
                print(f"[DEBUG] {msg}")
                if logger: logger.log("SECURITY_ALERT", msg)
            else:
                self.db.add_trusted_peer(ip, stored_username or "Unknown", fingerprint)
        else:
            self.db.add_trusted_peer(ip, "Unknown", fingerprint)

    def handle_client(self, client, addr):
        """Handle a client connection.
        Includes optional IP whitelist enforcement and granular permissions.
        """
        if not audit.get_logger():
            audit.init_logger(self.db)
        logger = audit.get_logger()
        try:
            client.settimeout(10)

            # Granular Access Control: Check if blocked
            permissions = self.db.get_peer_permissions(addr[0]) if self.db else {'can_chat': 1, 'can_list_files': 1, 'can_download_files': 1, 'is_blocked': 0}
            if permissions.get('is_blocked'):
                if logger: logger.log("SECURITY_ALERT", f"File transfer request from blocked peer {addr[0]} rejected.")
                return

            # IP whitelist check
            if self.allowed_ips is not None and addr[0] not in self.allowed_ips:
                if logger: logger.log("SECURITY_ALERT", f"File transfer connection from {addr[0]} rejected: IP not allowed.")
                client.sendall(json.dumps({'status': 'ERR', 'msg': 'IP not allowed'}).encode())
                return

            header_raw = client.recv(4096).decode()
            if not header_raw:
                return

            try:
                req = json.loads(header_raw)
                if not isinstance(req, dict):
                     if logger: logger.log("SECURITY_ALERT", f"Malformed file request from {addr[0]}: Not a JSON object.")
                     return
            except json.JSONDecodeError:
                if logger: logger.log("SECURITY_ALERT", f"Malformed file request from {addr[0]}: Invalid JSON.")
                print(f"[DEBUG] File server received invalid JSON header")
                return

            # Simple token authentication if enabled
            if self.auth_token is not None:
                if req.get('token') != self.auth_token:
                    if logger: logger.log("AUTH_FAILURE", f"File transfer authentication failed for {addr[0]}.")
                    client.sendall(json.dumps({'status': 'ERR', 'msg': 'Authentication failed'}).encode())
                    return
                # token matches – continue processing
            cmd = req.get('cmd')
            if not isinstance(cmd, str): return

            if cmd == 'PUSH_FILE':
                # PUSH_FILE is someone sending to us.
                # We could have a can_receive_files permission, but for now we'll allow it if not blocked.
                filename = req.get('filename')
                size = req.get('size')
                if not isinstance(filename, str) or not isinstance(size, int): return
                filename = os.path.basename(filename.replace("\\", "/"))
                if not filename or filename in ("..", "."): return
                if logger: logger.log("FILE_TRANSFER", f"Receiving file '{filename}' ({size} bytes) from {addr[0]}.")
                client.sendall(b'ACK')
                self.receive_stream(client, filename, size)

            elif cmd == 'PULL_FILE':
                # Enforce Permission
                if not permissions.get('can_download_files'):
                    if logger: logger.log("SECURITY_ALERT", f"PULL_FILE from {addr[0]} blocked due to permissions.")
                    client.sendall(json.dumps({'status': 'ERR', 'msg': 'Access denied'}).encode())
                    return

                path = req.get('path')
                if not isinstance(path, str):
                    if logger: logger.log("SECURITY_ALERT", f"Malformed PULL_FILE request from {addr[0]}: path must be a string.")
                    return

                # Security: Check if file is shared and not expired
                if not self.db.is_file_shared(path):
                    if logger: logger.log("SECURITY_ALERT", f"Blocked unauthorized PULL_FILE request from {addr[0]}: {path}")
                    client.sendall(json.dumps({'status': 'ERR', 'msg': 'Access denied'}).encode())
                    return

                # Sanitize path to prevent directory traversal (Defense in Depth)
                if ".." in path:
                    if logger: logger.log("SECURITY_ALERT", f"Blocked potential directory traversal attempt from {addr[0]}: {path}")
                    client.sendall(json.dumps({'status': 'ERR', 'msg': 'Access denied'}).encode())
                    return
                    return

                if os.path.exists(path) and os.path.isfile(path):
                    if logger: logger.log("FILE_TRANSFER", f"Sending file '{path}' to {addr[0]}.")
                    size = os.path.getsize(path)
                    client.sendall(json.dumps({'status': 'OK', 'size': size}).encode())
                    ack = client.recv(1024)
                    with open(path, 'rb') as f:
                        while True:
                            # Use 64KB buffer for faster disk I/O and network sends
                            data = f.read(65536)
                            if not data: break
                            client.sendall(data)
                else:
                    if logger: logger.log("SECURITY_ALERT", f"Requested file '{path}' not found or expired for {addr[0]}.")
                    client.sendall(json.dumps({'status': 'ERR', 'msg': 'File not found or expired'}).encode())

            elif cmd == 'LIST_SHARED':
                # Enforce Permission
                if not permissions.get('can_list_files'):
                    if logger: logger.log("SECURITY_ALERT", f"LIST_SHARED from {addr[0]} blocked due to permissions.")
                    client.sendall(json.dumps({'status': 'ERR', 'msg': 'Access denied'}).encode())
                    return

                files = self.db.get_files()
                file_list = []
                for f in files:
                    # f structure: (id, filename, path, size, owner_ip, is_folder, checksum)
                    file_list.append({
                        'filename': f[1],
                        'path': f[2],
                        'size': f[3],
                        'is_folder': f[5],
                        'owner': f[4],
                        'checksum': f[6] if len(f) > 6 else None
                    })
                data_encoded = json.dumps(file_list).encode()
                client.sendall(json.dumps({'status': 'OK', 'size': len(data_encoded)}).encode())
                ack = client.recv(1024)
                client.sendall(data_encoded)

            elif cmd == 'LIST_FOLDER':
                # Enforce Permission
                if not permissions.get('can_list_files'):
                    if logger: logger.log("SECURITY_ALERT", f"LIST_FOLDER from {addr[0]} blocked due to permissions.")
                    client.sendall(json.dumps({'status': 'ERR', 'msg': 'Access denied'}).encode())
                    return

                # Use pathlib for OS‑independent path handling and include directories in the listing
                path_str = req.get('path')
                if not isinstance(path_str, str):
                    if logger: logger.log("SECURITY_ALERT", f"Malformed LIST_FOLDER request from {addr[0]}: path must be a string.")
                    return
                base_path = Path(path_str)
                if base_path.exists() and base_path.is_dir():
                    entries = []
                    for entry in base_path.rglob('*'):
                        rel_path = entry.relative_to(base_path).as_posix()
                        if entry.is_file():
                            entries.append({
                                'type': 'file',
                                'rel_path': rel_path,
                                'size': entry.stat().st_size,
                                'checksum': self.calculate_sha256(str(entry))
                            })
                        elif entry.is_dir():
                            entries.append({
                                'type': 'dir',
                                'rel_path': rel_path,
                                'size': 0
                            })
                    data_encoded = json.dumps(entries).encode()
                    client.sendall(json.dumps({'status': 'OK', 'size': len(data_encoded)}).encode())
                    ack = client.recv(1024)
                    client.sendall(data_encoded)
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
                # Use 64KB buffer for faster network receives and disk writes
                data = sock.recv(min(65536, size - received))
                if not data:
                    raise ConnectionError("Connection closed prematurely")
                f.write(data)
                received += len(data)
        print(f"[DEBUG] Received {filename}")

    def download_file(self, target_ip, remote_path, expected_checksum=None, target_port=None):
        filename = os.path.basename(remote_path)
        try:
            port = target_port if target_port else self.port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
                raw.settimeout(10)
                raw.connect((target_ip, port))
                s = wrap_socket(raw)

                # TOFU: check peer fingerprint
                fingerprint = get_peer_fingerprint(s)
                if fingerprint:
                    self._check_tofu(target_ip, fingerprint)

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

                    # Verify integrity
                    local_path = os.path.join(self.save_dir, filename)
                    if expected_checksum:
                        actual_checksum = self.calculate_sha256(local_path)
                        logger = audit.get_logger()
                        if actual_checksum == expected_checksum:
                            print(f"[DEBUG] Integrity verified for {filename}")
                            if logger: logger.log("FILE_INTEGRITY_SUCCESS", f"File: {filename}, Hash: {actual_checksum}")
                        else:
                            print(f"[DEBUG] Integrity FAILURE for {filename}")
                            if logger: logger.log("FILE_INTEGRITY_FAILURE", f"File: {filename}, Expected: {expected_checksum}, Got: {actual_checksum}")
                            try:
                                os.remove(local_path)
                                print(f"[DEBUG] Deleted corrupted file: {filename}")
                            except Exception as delete_err:
                                print(f"[DEBUG] Failed to delete corrupted file {filename}: {delete_err}")
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
                s = wrap_socket(raw)

                # TOFU: check peer fingerprint
                fingerprint = get_peer_fingerprint(s)
                if fingerprint:
                    self._check_tofu(target_ip, fingerprint)

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
                data = self._recv_all(s, size)
                file_list = json.loads(data)

            # Filter only files
            files = [f for f in file_list if f.get('type') == 'file']
            total_files = len(files)
            for idx, item in enumerate(files, start=1):
                rel_path = item['rel_path']
                expected_checksum = item.get('checksum')
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
                                                    overall_total=total_files,
                                                    expected_checksum=expected_checksum)
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
                            per_file_cb=None, overall_index=0, overall_total=1, expected_checksum=None):
        """Download a single file with optional per‑file progress callback.
        Returns *True* on success, *False* on any error.
        Uses pathlib for cross‑platform path handling and includes auth token if set.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
                raw.settimeout(10)
                raw.connect((target_ip, self.port))
                s = wrap_socket(raw)
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
                            # Use 64KB buffer
                            chunk = s.recv(min(65536, size - received))
                            if not chunk:
                                raise ConnectionError("Connection closed prematurely")
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

                    # Verify integrity
                    if expected_checksum:
                        actual_checksum = self.calculate_sha256(str(local_path))
                        logger = audit.get_logger()
                        if actual_checksum == expected_checksum:
                            print(f"[DEBUG] Integrity verified for {rel_path}")
                            if logger: logger.log("FILE_INTEGRITY_SUCCESS", f"File: {rel_path}, Hash: {actual_checksum}")
                        else:
                            print(f"[DEBUG] Integrity FAILURE for {rel_path}")
                            if logger: logger.log("FILE_INTEGRITY_FAILURE", f"File: {rel_path}, Expected: {expected_checksum}, Got: {actual_checksum}")
                            try:
                                local_path.unlink(missing_ok=True)
                                print(f"[DEBUG] Deleted corrupted file: {rel_path}")
                            except Exception as delete_err:
                                print(f"[DEBUG] Failed to delete corrupted file {rel_path}: {delete_err}")
                            return False # Consider integrity failure a download failure

                    return True
                else:
                    print(f"[DEBUG] File {rel_path} download error: {resp.get('msg')}")
                    return False
        except Exception as e:
            print(f"[DEBUG] File {rel_path} download error: {e}")
            return False

    def _recv_all(self, sock, size):
        """Efficiently receive exactly *size* bytes from a socket using b''.join()."""
        chunks = []
        received = 0
        while received < size:
            # Use a larger 64KB buffer to reduce syscalls
            chunk = sock.recv(min(65536, size - received))
            if not chunk:
                raise ConnectionError("Connection closed prematurely")
            chunks.append(chunk)
            received += len(chunk)
        return b"".join(chunks)

    def get_shared_files(self, target_ip, target_port=None):
        try:
            port = target_port if target_port else self.port
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
                raw.settimeout(5)
                raw.connect((target_ip, port))
                s = wrap_socket(raw)

                # TOFU: check peer fingerprint
                fingerprint = get_peer_fingerprint(s)
                if fingerprint:
                    self._check_tofu(target_ip, fingerprint)

                payload = {'cmd': 'LIST_SHARED'}
                if self.auth_token is not None:
                    payload['token'] = self.auth_token
                s.sendall(json.dumps(payload).encode())
                resp_raw = s.recv(4096).decode()
                resp = json.loads(resp_raw)
                if resp.get('status') == 'OK':
                    size = resp.get('size')
                    s.sendall(b'ACK')
                    data = self._recv_all(s, size)
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
