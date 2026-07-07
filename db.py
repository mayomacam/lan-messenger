import sqlite3
import uuid
import time
import threading
import os
import base64
import functools
from typing import List, Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend

class EncryptionManager:
    def __init__(self, key_file=".master.key", password=None):
        self.key_file = key_file
        self.key = None
        self.aesgcm = None
        if password:
            self.unlock(password)

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600000,
            backend=default_backend()
        )
        return kdf.derive(password.encode())

    def unlock(self, password: str):
        """Unlocks the master key using the provided password."""
        if os.path.exists(self.key_file):
            with open(self.key_file, "rb") as f:
                data = f.read()

            # Migration check: if file is exactly 32 bytes, it's an old unencrypted key
            if len(data) == 32:
                self.key = data
                # Re-save encrypted
                self._save_encrypted_key(password, self.key)
            elif len(data) != 76:
                raise ValueError("Corrupted key file: invalid file size.")
            else:
                try:
                    # Format: salt(16) + nonce(12) + encrypted_key(32 + 16 for tag) = 76 bytes
                    salt = data[:16]
                    nonce = data[16:28]
                    ciphertext = data[28:]

                    pw_key = self._derive_key(password, salt)
                    aesgcm_pw = AESGCM(pw_key)
                    self.key = aesgcm_pw.decrypt(nonce, ciphertext, None)
                except Exception as e:
                    raise ValueError("Invalid password or corrupted key file.") from e
        else:
            # Generate new key
            self.key = AESGCM.generate_key(bit_length=256)
            self._save_encrypted_key(password, self.key)

        self.aesgcm = AESGCM(self.key)

    def _save_encrypted_key(self, password: str, key: bytes):
        salt = os.urandom(16)
        nonce = os.urandom(12)
        pw_key = self._derive_key(password, salt)
        aesgcm_pw = AESGCM(pw_key)
        ciphertext = aesgcm_pw.encrypt(nonce, key, None)

        data = salt + nonce + ciphertext
        try:
            fd = os.open(self.key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        except Exception:
            with open(self.key_file, "wb") as f:
                f.write(data)
            try:
                os.chmod(self.key_file, 0o600)
            except Exception:
                pass

    def encrypt(self, data: str) -> str:
        if not self.aesgcm: return data # Return plaintext if locked (should not happen in normal flow)
        if not data: return ""
        if self.is_locked():
            raise RuntimeError("Database is locked.")
        nonce = os.urandom(12)
        ciphertext = self.aesgcm.encrypt(nonce, data.encode(), None)
        return "enc:" + base64.b64encode(nonce + ciphertext).decode()

    @functools.lru_cache(maxsize=1024)
    def decrypt(self, encrypted_data: str) -> str:
        if not self.aesgcm: return encrypted_data
        if not encrypted_data: return ""
        if not encrypted_data.startswith("enc:"):
            return encrypted_data
        if self.is_locked():
            return "[Locked]"
        try:
            raw_data = base64.b64decode(encrypted_data[4:])
            nonce = raw_data[:12]
            ciphertext = raw_data[12:]
            return self.aesgcm.decrypt(nonce, ciphertext, None).decode()
        except Exception:
            return "[Decryption Failed]"

    def is_locked(self) -> bool:
        return self.aesgcm is None

    def needs_setup(self) -> bool:
        return not os.path.exists(self.key_file)

    def lock(self):
        self.key = None
        self.aesgcm = None

    def setup(self, password: str):
        self.unlock(password)

class Database:
    def __init__(self, password, db_name="lan_messenger.db", key_file=".master.key"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.lock = threading.Lock()
        self.cipher = EncryptionManager(password=password, key_file=key_file)
        # Initialize internal cache for peer permissions to avoid repeated DB hits
        self._get_peer_permissions_internal = functools.lru_cache(maxsize=128)(self._get_peer_permissions_internal_raw)
        self._enable_wal_mode()
        self.create_tables()

    def is_locked(self) -> bool:
        return self.cipher.is_locked()

    def needs_setup(self) -> bool:
        return self.cipher.needs_setup()

    def setup(self, password: str):
        self.cipher.setup(password)

    def unlock(self, password: str) -> bool:
        return self.cipher.unlock(password)

    def lock_db(self):
        self.cipher.lock()

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

            # Trusted Peers table: ip, username, fingerprint, trust_level, is_blocked, can_chat, can_list_files, can_download_files, last_seen
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
                    last_seen REAL,
                    is_verified INTEGER DEFAULT 0
                )
            """)
            # Migration for existing installations
            cursor.execute("PRAGMA table_info(trusted_peers)")
            tp_columns = [info[1] for info in cursor.fetchall()]
            if 'is_verified' not in tp_columns:
                cursor.execute("ALTER TABLE trusted_peers ADD COLUMN is_verified INTEGER DEFAULT 0")
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

            # Audit Logs table: id, event_type, details, timestamp
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
                    AND (recipient = ? OR (sender = ? AND recipient IS NOT NULL))
                    AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY timestamp DESC LIMIT ?
                """, (peer_ip, peer_ip, now, limit))
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
            # Invalidate the permissions cache whenever peer data changes
            self._get_peer_permissions_internal.cache_clear()
            with self.conn:
                cursor = self.conn.execute("SELECT trust_level FROM trusted_peers WHERE ip = ?", (ip,))
                row = cursor.fetchone()

                if row:
                    final_trust = trust_level if trust_level is not None else row[0]
                    self.conn.execute("""
                        UPDATE trusted_peers SET username = ?, fingerprint = ?, trust_level = ?, last_seen = ?
                        WHERE ip = ?
                    """, (username, fingerprint, final_trust, now, ip))
                else:
                    final_trust = trust_level if trust_level is not None else 'untrusted'
                    self.conn.execute("""
                        INSERT INTO trusted_peers (ip, username, fingerprint, trust_level, last_seen)
                        VALUES (?, ?, ?, ?, ?)
                    """, (ip, username, fingerprint, final_trust, now))

    def get_trusted_peer(self, ip: str) -> Tuple:
        with self.lock:
            cursor = self.conn.execute("""
                SELECT ip, username, fingerprint, trust_level, is_blocked, can_chat, can_list_files, can_download_files, last_seen, is_verified
                FROM trusted_peers WHERE ip = ?
            """, (ip,))
            return cursor.fetchone()

    def _get_peer_permissions_internal_raw(self, ip: str) -> dict:
        """Internal uncached helper to fetch peer permissions."""
        peer = self.get_trusted_peer(ip)
        if not peer:
            return {'is_blocked': 0, 'can_chat': 1, 'can_list_files': 1, 'can_download_files': 1, 'is_verified': 0}
        return {
            'is_blocked': peer[4],
            'can_chat': peer[5],
            'can_list_files': peer[6],
            'can_download_files': peer[7],
            'is_verified': peer[9]
        }

    def get_peer_permissions(self, ip: str) -> dict:
        """Get permissions for a peer, utilizing the LRU cache."""
        return self._get_peer_permissions_internal(ip)

    def update_peer_permissions(self, ip: str, permissions: dict):
        with self.lock:
            # Invalidate cache before update
            self._get_peer_permissions_internal.cache_clear()
            with self.conn:
                self.conn.execute("""
                    UPDATE trusted_peers
                    SET is_blocked = ?, can_chat = ?, can_list_files = ?, can_download_files = ?, is_verified = ?
                    WHERE ip = ?
                """, (
                    permissions.get('is_blocked', 0),
                    permissions.get('can_chat', 1),
                    permissions.get('can_list_files', 1),
                    permissions.get('can_download_files', 1),
                    permissions.get('is_verified', 0),
                    ip
                ))

    def get_peer_trust_levels(self, ips: List[str]) -> dict:
        if not ips: return {}
        placeholders = ",".join(["?"] * len(ips))
        with self.lock:
            cursor = self.conn.execute(f"SELECT ip, trust_level FROM trusted_peers WHERE ip IN ({placeholders})", ips)
            return {row[0]: row[1] for row in cursor.fetchall()}

    def get_peers_permissions(self, ips: List[str]) -> dict:
        if not ips: return {}
        placeholders = ",".join(["?"] * len(ips))
        with self.lock:
            cursor = self.conn.execute(f"""
                SELECT ip, can_chat, can_list_files, can_download_files, is_blocked, is_verified
                FROM trusted_peers WHERE ip IN ({placeholders})
            """, ips)
            results = {}
            for row in cursor.fetchall():
                results[row[0]] = {
                    'can_chat': bool(row[1]),
                    'can_list_files': bool(row[2]),
                    'can_download_files': bool(row[3]),
                    'is_blocked': bool(row[4]),
                    'is_verified': bool(row[5])
                }
            return results

    def update_peer_trust(self, ip: str, trust_level: str):
        with self.lock:
            # Trust changes should also invalidate the permissions cache
            self._get_peer_permissions_internal.cache_clear()
            with self.conn:
                self.conn.execute("UPDATE trusted_peers SET trust_level = ? WHERE ip = ?", (trust_level, ip))

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

