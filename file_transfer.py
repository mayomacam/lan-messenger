import socket
import threading
import os
import json
import time
from constants import TCP_FILE_PORT, BUFFER_SIZE

class FileTransferManager:
    def __init__(self, db, port, save_dir="downloads"):
        self.db = db
        self.port = port
        self.save_dir = save_dir
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind(('0.0.0.0', self.port))
        self.server_socket.listen(5)
        self.running = True
        threading.Thread(target=self.start_server, daemon=True).start()

    def start_server(self):
        while self.running:
            try:
                client, addr = self.server_socket.accept()
                threading.Thread(target=self.handle_client, args=(client,)).start()
            except:
                pass

    def handle_client(self, client):
        try:
            # Protocol: COMMAND|ARGS...
            header = client.recv(1024).decode()
            if not header: return
            parts = header.split('|')
            cmd = parts[0]
            
            if cmd == 'PUSH_FILE':
                # PUSH_FILE|filename|size
                filename, size = parts[1], int(parts[2])
                client.send(b'ACK')
                self.receive_stream(client, filename, size)
            
            elif cmd == 'PULL_FILE':
                # PULL_FILE|path
                path = parts[1]
                if os.path.exists(path) and os.path.isfile(path):
                    size = os.path.getsize(path)
                    client.send(f"OK|{size}".encode())
                    ack = client.recv(1024) # Wait for ACK
                    with open(path, 'rb') as f:
                        while True:
                            data = f.read(BUFFER_SIZE)
                            if not data: break
                            client.send(data)
                else:
                    client.send(b'ERR|File not found')
            
            elif cmd == 'LIST_SHARED':
                # Returns JSON list of all shared files from DB
                # Schema: [{'filename': ..., 'size': ..., 'is_folder': ..., 'path': ...}]
                files = self.db.get_files()
                # f: id, filename, path, size, owner_ip, is_folder
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
                client.send(f"OK|{len(data)}".encode())
                ack = client.recv(1024)
                client.send(data.encode())
            
            elif cmd == 'LIST_FOLDER':
                # LIST_FOLDER|path
                path = parts[1]
                if os.path.exists(path) and os.path.isdir(path):
                    files = []
                    for r, d, f in os.walk(path):
                        for file in f:
                            full_path = os.path.join(r, file)
                            rel_path = os.path.relpath(full_path, path)
                            files.append({'rel_path': rel_path, 'size': os.path.getsize(full_path)})
                    data = json.dumps(files)
                    client.send(f"OK|{len(data)}".encode())
                    ack = client.recv(1024)
                    client.send(data.encode())
                else:
                    client.send(b'ERR|Folder not found')
                    
        except Exception as e:
            print(f"Error handling file client: {e}")
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
                data = sock.recv(min(BUFFER_SIZE, size - received))
                if not data: break
                f.write(data)
                received += len(data)
        print(f"Received {filename}")

    # Client methods
    def send_file(self, target_ip, file_path):
        if not os.path.exists(file_path): return
        filename = os.path.basename(file_path)
        size = os.path.getsize(file_path)
        
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((target_ip, self.port))
                s.send(f"PUSH_FILE|{filename}|{size}".encode())
                ack = s.recv(1024)
                if ack == b'ACK':
                    with open(file_path, 'rb') as f:
                        while True:
                            data = f.read(BUFFER_SIZE)
                            if not data: break
                            s.sendall(data)
        except Exception as e:
            print(f"Send file error: {e}")

    def download_file(self, target_ip, remote_path):
        filename = os.path.basename(remote_path)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((target_ip, self.port))
                s.send(f"PULL_FILE|{remote_path}".encode())
                resp = s.recv(1024).decode()
                if resp.startswith("OK"):
                    size = int(resp.split('|')[1])
                    s.send(b'ACK')
                    self.receive_stream(s, filename, size)
                else:
                    print(f"Download failed: {resp}")
        except Exception as e:
            print(f"Download error: {e}")

    def download_folder(self, target_ip, remote_path):
        folder_name = os.path.basename(remote_path)
        try:
            # 1. Get List
            file_list = []
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((target_ip, self.port))
                s.send(f"LIST_FOLDER|{remote_path}".encode())
                resp = s.recv(1024).decode()
                if resp.startswith("OK"):
                    size = int(resp.split('|')[1])
                    s.send(b'ACK')
                    data = b""
                    while len(data) < size:
                        data += s.recv(4096)
                    file_list = json.loads(data)
                else:
                    print(f"Folder list failed: {resp}")
                    return

            # 2. Download each file
            for item in file_list:
                rel_path = item['rel_path']
                remote_file_path = os.path.join(remote_path, rel_path).replace("\\", "/") # Ensure path format
                
                # Careful with path joining on different OS, but assuming internal consistency
                # Actually, remote_path might use backslashes on Windows sender.
                # The sender provided rel_path.
                # We need to request the specific file.
                # If we send PULL_FILE with 'remote_path + rel_path', the sender sees that absolute path.
                # To make this robust, 'PULL_FILE' takes the absolute path on sender.
                # So we construct it:
                
                # Handling path separators: Sender sent rel_path. 
                # If sender is Windows, rel_path has backslashes.
                # If receiver is Linux, we just treat it as a string for the request?
                # Yes, but for local saving we need to adapt.
                
                # Local save:
                local_rel_path = rel_path # Used for local structure
                
                # Request:
                # We need to know 'remote_root'. 
                # Logic: remote_file = os.path.join(remote_path, rel_path) (using sender's separator logic hopefully?)
                # Actually safest is to construct it using string concatenation if we know the separator, 
                # but os.path.join on client side matches client OS.
                # If client and server different OS, this might fail.
                # Assumption: Homogeneous LAN or Python handles it? 
                # Python's os.path.join uses local separator.
                # If server is Windows, it needs backslashes. If client is Linux, it joins with slash.
                # Sending "C:\Foo/Bar" might work or might not.
                # Ideally, we should request by ID or have a cleaner protocol.
                # But for now, let's assume similar OS or basic slash compatibility (Windows handles forward slashes mostly).
                
                # A safer bet: The server should handle the path resolving.
                # But 'PULL_FILE' takes a path.
                
                full_remote_path = remote_path + "/" + rel_path.replace("\\", "/") # Force forward slash might be safer if server handles it?
                # Let's just use string join and hope for best or assume Windows as per user metadata.
                # User is on Windows.
                full_remote_path = os.path.join(remote_path, rel_path)
                
                self._download_file_direct(target_ip, full_remote_path, folder_name, rel_path)
                
        except Exception as e:
            print(f"Folder download error: {e}")

    def _download_file_direct(self, target_ip, remote_path, folder_name, rel_path):
        # Downloads file into save_dir/folder_name/rel_path
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((target_ip, self.port))
                s.send(f"PULL_FILE|{remote_path}".encode())
                resp = s.recv(1024).decode()
                if resp.startswith("OK"):
                    size = int(resp.split('|')[1])
                    s.send(b'ACK')
                    
                    # Determine local path
                    local_file_path = os.path.join(self.save_dir, folder_name, rel_path)
                    local_folder = os.path.dirname(local_file_path)
                    if not os.path.exists(local_folder):
                        os.makedirs(local_folder)
                        
                    received = 0
                    with open(local_file_path, 'wb') as f:
                        while received < size:
                            data = s.recv(min(BUFFER_SIZE, size - received))
                            if not data: break
                            f.write(data)
                            received += len(data)
                    print(f"Downloaded {rel_path}")
        except Exception as e:
             print(f"File {rel_path} download error: {e}")

    def get_shared_files(self, target_ip):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((target_ip, self.port))
                s.send(b"LIST_SHARED|")
                resp = s.recv(1024).decode()
                if resp.startswith("OK"):
                    size = int(resp.split('|')[1])
                    s.send(b'ACK')
                    data = b""
                    while len(data) < size:
                        data += s.recv(4096)
                    return json.loads(data)
        except Exception as e:
            print(f"Get shared files error: {e}")
        return []

    def close(self):
        self.running = False
        self.server_socket.close()
