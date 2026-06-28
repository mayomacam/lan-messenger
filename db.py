import sqlite3
import uuid
import time
import threading
import os
import base64
import functools
from typing import List, Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend

class EncryptionManager:
    def __init__(self, password: str, key_file=".master.key"):
        self.key_file = key_file
        self.password = password
        self.key = self._load_or_generate_key(password)
        self.aesgcm = AESGCM(self.key)

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600000,
            backend=default_backend()
        )
        return kdf.derive(password.encode())

    def _load_or_generate_key(self, password: str):
        if os.path.exists(self.key_file):
            with open(self.key_file, "rb") as f:
                data = f.read()
                if len(data) < 28: # Salt(16) + Nonce(12)
                    raise ValueError("Master key file is corrupted or too short.")
                salt = data[:16]
                nonce = data[16:28]
                encrypted_key = data[28:]

                derived_key = self._derive_key(password, salt)
                kek = AESGCM(derived_key) # Key Encryption Key
                try:
                    return kek.decrypt(nonce, encrypted_key, None)
                except Exception:
                    raise ValueError("Invalid Master Password.")
        else:
            # Generate a new random master key
            master_key = AESGCM.generate_key(bit_length=256)
            salt = os.urandom(16)
            nonce = os.urandom(12)

            derived_key = self._derive_key(password, salt)
            kek = AESGCM(derived_key)
            encrypted_key = kek.encrypt(nonce, master_key, None)

            try:
                fd = os.open(self.key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with open(fd, "wb") as f:
                    f.write(salt + nonce + encrypted_key)
            except Exception:
                with open(self.key_file, "wb") as f:
                    f.write(salt + nonce + encrypted_key)
                try:
                    os.chmod(self.key_file, 0o600)
                except Exception:
                    pass
            return master_key

    def encrypt(self, data: str) -> str:
        if not data: return ""
        nonce = os.urandom(12)
        ciphertext = self.aesgcm.encrypt(nonce, data.encode(), None)
        return "enc:" + base64.b64encode(nonce + ciphertext).decode()

    @functools.lru_cache(maxsize=1024)
    def decrypt(self, encrypted_data: str) -> str:
        if not encrypted_data: return ""
        if not encrypted_data.startswith("enc:"):
            return encrypted_data
        try:
            raw_data = base64.b64decode(encrypted_data[4:])
            nonce = raw_data[:12]
            ciphertext = raw_data[12:]
            return self.aesgcm.decrypt(nonce, ciphertext, None).decode()
        except Exception:
            return "[Decryption Failed]"

class Database:
    def __init__(self, password: str, db_name="lan_messenger.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.lock = threading.Lock()
        self.cipher = EncryptionManager(password)
        self._enable_wal_mode()
        self.create_tables()

    def _enable_wal_mode(self):
        """Enable Write-Ahead Logging for better concurrency and performance."""
        with self.lock:
            # WAL mode allows concurrent reads and writes
            self.conn.execute("PRAGMA journal_mode=WAL")
            # NORMAL synchronous mode is faster and still safe enough with WAL
            self.conn.execute("PRAGMA synchronous=NORMAL")

    def create_tables(self):
        with self.lock:
            cursor = self.conn.cursor()
            # Messages table: id, sender, content, timestamp, is_deleted, recipient, expires_at
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    content TEXT,
                    timestamp REAL NOT NULL,
                    is_deleted BOOLEAN DEFAULT 0,
                    recipient TEXT,
                    expires_at REAL
                )
            """)
            # Migration: add recipient column if it doesn't exist
            cursor.execute("PRAGMA table_info(messages)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'recipient' not in columns:
                cursor.execute("ALTER TABLE messages ADD COLUMN recipient TEXT")
            if 'expires_at' not in columns:
                cursor.execute("ALTER TABLE messages ADD COLUMN expires_at REAL")

            # Optimized composite index for faster message retrieval by recipient, status, and timestamp
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_recipient_deleted_ts ON messages(recipient, is_deleted, timestamp)")
            # Index for expiring messages
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_expires_at ON messages(expires_at)")

            # Files table: id, filename, path, size, owner_ip, is_folder, checksum, expires_at
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER,
                    owner_ip TEXT NOT NULL,
                    is_folder BOOLEAN DEFAULT 0,
                    checksum TEXT,
                    expires_at REAL
                )
            """)

            # Migration: add columns to files table if they don't exist
            cursor.execute("PRAGMA table_info(files)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'checksum' not in columns:
                cursor.execute("ALTER TABLE files ADD COLUMN checksum TEXT")
            if 'expires_at' not in columns:
                cursor.execute("ALTER TABLE files ADD COLUMN expires_at REAL")

            # Trusted Peers table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trusted_peers (
                    ip TEXT PRIMARY KEY,
                    username TEXT,
                    fingerprint TEXT,
                    trust_level TEXT DEFAULT 'untrusted',
                    is_blocked BOOLEAN DEFAULT 0,
                    can_chat BOOLEAN DEFAULT 1,
                    can_list_files BOOLEAN DEFAULT 1,
                    can_download_files BOOLEAN DEFAULT 1,
                    last_seen REAL
                )
            """)
            # Migration for existing installations
            cursor.execute("PRAGMA table_info(trusted_peers)")
            tp_columns = [info[1] for info in cursor.fetchall()]
            if 'username' not in tp_columns:
                cursor.execute("ALTER TABLE trusted_peers ADD COLUMN username TEXT")
            if 'trust_level' not in tp_columns:
                cursor.execute("ALTER TABLE trusted_peers ADD COLUMN trust_level TEXT DEFAULT 'untrusted'")
            if 'is_blocked' not in tp_columns:
                cursor.execute("ALTER TABLE trusted_peers ADD COLUMN is_blocked BOOLEAN DEFAULT 0")
            if 'can_chat' not in tp_columns:
                cursor.execute("ALTER TABLE trusted_peers ADD COLUMN can_chat BOOLEAN DEFAULT 1")
            if 'can_list_files' not in tp_columns:
                cursor.execute("ALTER TABLE trusted_peers ADD COLUMN can_list_files BOOLEAN DEFAULT 1")
            if 'can_download_files' not in tp_columns:
                cursor.execute("ALTER TABLE trusted_peers ADD COLUMN can_download_files BOOLEAN DEFAULT 1")

            # Audit Logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    details TEXT,
                    timestamp REAL NOT NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp)")

            self.conn.commit()

    def add_message(self, sender: str, content: str, recipient: str = None, ttl: int = None) -> str:
        msg_id = str(uuid.uuid4())
        timestamp = time.time()
        expires_at = timestamp + ttl if ttl else None
        encrypted_content = self.cipher.encrypt(content)
        with self.lock:
            with self.conn:
                self.conn.execute("INSERT INTO messages (id, sender, content, timestamp, recipient, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                                 (msg_id, sender, encrypted_content, timestamp, recipient, expires_at))
        return msg_id

    def add_received_message(self, msg_id: str, sender: str, content: str, timestamp: float, recipient: str = None, expires_at: float = None):
        encrypted_content = self.cipher.encrypt(content)
        with self.lock:
            with self.conn:
                self.conn.execute("INSERT OR IGNORE INTO messages (id, sender, content, timestamp, recipient, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                                 (msg_id, sender, encrypted_content, timestamp, recipient, expires_at))

    def get_messages(self, limit=50, peer_ip: str = None) -> List[Tuple]:
        now = time.time()
        with self.lock:
            if peer_ip:
                cursor = self.conn.execute("""
                    SELECT id, sender, content, timestamp, is_deleted, recipient, expires_at
                    FROM messages
                    WHERE is_deleted = 0
                    AND recipient = ?
                    AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY timestamp DESC LIMIT ?
                """, (peer_ip, now, limit))
            else:
                cursor = self.conn.execute("""
                    SELECT id, sender, content, timestamp, is_deleted, recipient, expires_at
                    FROM messages
                    WHERE is_deleted = 0 AND recipient IS NULL
                    AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY timestamp DESC LIMIT ?
                """, (now, limit))

            rows = cursor.fetchall()

        decrypted_rows = []
        for row in rows:
            decrypted_content = self.cipher.decrypt(row[2])
            decrypted_rows.append((row[0], row[1], decrypted_content, row[3], row[4], row[5], row[6]))
        return decrypted_rows[::-1]

    def delete_message(self, msg_id: str):
        with self.lock:
            with self.conn:
                self.conn.execute("UPDATE messages SET is_deleted = 1 WHERE id = ?", (msg_id,))

    def edit_message(self, msg_id: str, new_content: str):
        encrypted_content = self.cipher.encrypt(new_content)
        with self.lock:
            with self.conn:
                self.conn.execute("UPDATE messages SET content = ? WHERE id = ?", (encrypted_content, msg_id))

    def add_file(self, filename: str, path: str, size: int, owner_ip: str, is_folder: bool = False, checksum: str = None, ttl: int = None) -> str:
        file_id = str(uuid.uuid4())
        expires_at = time.time() + ttl if ttl else None
        encrypted_filename = self.cipher.encrypt(filename)
        encrypted_path = self.cipher.encrypt(path)
        with self.lock:
            with self.conn:
                self.conn.execute("INSERT INTO files (id, filename, path, size, owner_ip, is_folder, checksum, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                 (file_id, encrypted_filename, encrypted_path, size, owner_ip, is_folder, checksum, expires_at))
        return file_id

    def get_files(self) -> List[Tuple]:
        now = time.time()
        with self.lock:
            cursor = self.conn.execute("SELECT id, filename, path, size, owner_ip, is_folder, checksum, expires_at FROM files WHERE expires_at IS NULL OR expires_at > ?", (now,))
            rows = cursor.fetchall()

        decrypted_rows = []
        for row in rows:
            decrypted_filename = self.cipher.decrypt(row[1])
            decrypted_path = self.cipher.decrypt(row[2])
            decrypted_rows.append((row[0], decrypted_filename, decrypted_path, row[3], row[4], row[5], row[6], row[7]))
        return decrypted_rows

    def is_file_shared(self, path: str) -> bool:
        now = time.time()
        with self.lock:
            cursor = self.conn.execute("SELECT path, is_folder FROM files WHERE expires_at IS NULL OR expires_at > ?", (now,))
            rows = cursor.fetchall()

        norm_path = os.path.normpath(path)
        for row in rows:
            decrypted_shared_path = self.cipher.decrypt(row[0])
            is_folder = row[1]
            norm_shared = os.path.normpath(decrypted_shared_path)

            if is_folder:
                if norm_path == norm_shared or norm_path.startswith(norm_shared + os.sep):
                    return True
            else:
                if norm_path == norm_shared:
                    return True
        return False

    def delete_expired_files(self) -> int:
        now = time.time()
        with self.lock:
            with self.conn:
                cursor = self.conn.execute("DELETE FROM files WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
                return cursor.rowcount

    def delete_expired_messages(self) -> int:
        now = time.time()
        with self.lock:
            with self.conn:
                cursor = self.conn.execute("DELETE FROM messages WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
                return cursor.rowcount

    def add_trusted_peer(self, ip: str, username: str, fingerprint: str, trust_level: str = None):
        now = time.time()
        with self.lock:
            with self.conn:
                cursor = self.conn.execute("SELECT trust_level, can_chat, can_list_files, can_download_files, is_blocked FROM trusted_peers WHERE ip = ?", (ip,))
                row = cursor.fetchone()

                if row:
                    final_trust = trust_level if trust_level is not None else row[0]
                    self.conn.execute("""
                        UPDATE trusted_peers SET
                            username = ?,
                            fingerprint = ?,
                            trust_level = ?,
                            last_seen = ?
                        WHERE ip = ?
                    """, (username, fingerprint, final_trust, now, ip))
                else:
                    final_trust = trust_level if trust_level is not None else 'untrusted'
                    self.conn.execute("""
                        INSERT INTO trusted_peers (ip, username, fingerprint, trust_level, last_seen, can_chat, can_list_files, can_download_files, is_blocked)
                        VALUES (?, ?, ?, ?, ?, 1, 1, 1, 0)
                    """, (ip, username, fingerprint, final_trust, now))

    def get_peer_permissions(self, ip: str) -> dict:
        with self.lock:
            cursor = self.conn.execute("SELECT can_chat, can_list_files, can_download_files, is_blocked FROM trusted_peers WHERE ip = ?", (ip,))
            row = cursor.fetchone()
            if row:
                return {
                    'can_chat': bool(row[0]),
                    'can_list_files': bool(row[1]),
                    'can_download_files': bool(row[2]),
                    'is_blocked': bool(row[3])
                }
            return {'can_chat': True, 'can_list_files': True, 'can_download_files': True, 'is_blocked': False}

    def update_peer_permissions(self, ip: str, perms: dict):
        with self.lock:
            with self.conn:
                self.conn.execute("""
                    UPDATE trusted_peers SET
                        can_chat = ?, can_list_files = ?, can_download_files = ?, is_blocked = ?
                    WHERE ip = ?
                """, (int(perms.get('can_chat', True)),
                      int(perms.get('can_list_files', True)),
                      int(perms.get('can_download_files', True)),
                      int(perms.get('is_blocked', False)), ip))

    def get_trusted_peer(self, ip: str) -> Tuple:
        with self.lock:
            cursor = self.conn.execute("""
                SELECT ip, username, fingerprint, trust_level, is_blocked, can_chat, can_list_files, can_download_files, last_seen
                FROM trusted_peers WHERE ip = ?
            """, (ip,))
            return cursor.fetchone()

    def get_peer_trust_levels(self, ips: List[str]) -> dict:
        ips_list = list(ips)
        if not ips_list:
            return {}
        placeholders = ",".join(["?"] * len(ips_list))
        with self.lock:
            cursor = self.conn.execute(f"SELECT ip, trust_level FROM trusted_peers WHERE ip IN ({placeholders})", ips_list)
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_peers_permissions(self, ips: List[str]) -> dict:
        ips_list = list(ips)
        if not ips_list:
            return {}
        placeholders = ",".join(["?"] * len(ips_list))
        with self.lock:
            cursor = self.conn.execute(f"SELECT ip, can_chat, can_list_files, can_download_files, is_blocked FROM trusted_peers WHERE ip IN ({placeholders})", ips_list)
            return {row[0]: {
                'can_chat': bool(row[1]),
                'can_list_files': bool(row[2]),
                'can_download_files': bool(row[3]),
                'is_blocked': bool(row[4])
            } for row in cursor.fetchall()}

    def update_peer_trust(self, ip: str, trust_level: str):
        with self.lock:
            with self.conn:
                self.conn.execute("UPDATE trusted_peers SET trust_level = ? WHERE ip = ?", (trust_level, ip))

    def is_peer_blocked(self, ip: str) -> bool:
        with self.lock:
            cursor = self.conn.execute("SELECT is_blocked FROM trusted_peers WHERE ip = ?", (ip,))
            row = cursor.fetchone()
            return bool(row[0]) if row else False

    def add_audit_log(self, event_type: str, details: str):
        timestamp = time.time()
        with self.lock:
            try:
                with self.conn:
                    self.conn.execute("INSERT INTO audit_logs (event_type, details, timestamp) VALUES (?, ?, ?)",
                                     (event_type, details, timestamp))
            except Exception as e:
                print(f"[DEBUG] Failed to add audit log to DB: {e}")

    def get_audit_logs(self, limit=100) -> List[Tuple]:
        with self.lock:
            cursor = self.conn.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT ?", (limit,))
            return cursor.fetchall()

    def reap_expired_messages(self) -> int:
        return self.delete_expired_messages()

    def close(self):
        self.conn.close()

    def get_peers_permissions(self, ips: List[str]) -> dict:
        """Batch fetch permissions for multiple IPs."""
        ips_list = list(ips)
        if not ips_list:
            return {}
        placeholders = ",".join(["?"] * len(ips_list))
        with self.lock:
            cursor = self.conn.execute(f"SELECT ip, can_chat, can_list_files, can_download_files, is_blocked FROM trusted_peers WHERE ip IN ({placeholders})", ips_list)
            return {row[0]: {
                'can_chat': bool(row[1]),
                'can_list_files': bool(row[2]),
                'can_download_files': bool(row[3]),
                'is_blocked': bool(row[4])
            } for row in cursor.fetchall()}
