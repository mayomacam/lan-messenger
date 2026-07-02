import sqlite3
import uuid
import time
import threading
import os
import base64
import functools
from typing import List, Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class EncryptionManager:
    def __init__(self, key_file=".master.key"):
        self.key_file = key_file
        self.key = self._load_or_generate_key()
        self.aesgcm = AESGCM(self.key)

    def _load_or_generate_key(self):
        if os.path.exists(self.key_file):
            with open(self.key_file, "rb") as f:
                return f.read()
        else:
            key = AESGCM.generate_key(bit_length=256)
            try:
                fd = os.open(self.key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with open(fd, "wb") as f:
                    f.write(key)
            except Exception:
                with open(self.key_file, "wb") as f:
                    f.write(key)
                try:
                    os.chmod(self.key_file, 0o600)
                except Exception:
                    pass
            return key

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
    def __init__(self, db_name="lan_messenger.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.lock = threading.Lock()
        self.cipher = EncryptionManager()
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

            # Drop old less efficient indexes
            cursor.execute("DROP INDEX IF EXISTS idx_messages_deleted_timestamp")
            cursor.execute("DROP INDEX IF EXISTS idx_messages_recipient")

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

            # Trusted Peers table: ip, username, fingerprint, trust_level, permissions, last_seen
            # New installations use this schema
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trusted_peers (
                    ip TEXT PRIMARY KEY,
                    username TEXT,
                    fingerprint TEXT,
                    trust_level TEXT DEFAULT 'untrusted',
                    can_chat BOOLEAN DEFAULT 1,
                    can_list_files BOOLEAN DEFAULT 1,
                    can_download_files BOOLEAN DEFAULT 1,
                    is_blocked BOOLEAN DEFAULT 0,
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
            if 'can_chat' not in tp_columns:
                cursor.execute("ALTER TABLE trusted_peers ADD COLUMN can_chat BOOLEAN DEFAULT 1")
            if 'can_list_files' not in tp_columns:
                cursor.execute("ALTER TABLE trusted_peers ADD COLUMN can_list_files BOOLEAN DEFAULT 1")
            if 'can_download_files' not in tp_columns:
                cursor.execute("ALTER TABLE trusted_peers ADD COLUMN can_download_files BOOLEAN DEFAULT 1")
            if 'is_blocked' not in tp_columns:
                cursor.execute("ALTER TABLE trusted_peers ADD COLUMN is_blocked BOOLEAN DEFAULT 0")

            # Audit Logs table: id, event_type, details, timestamp
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    details TEXT,
                    timestamp REAL NOT NULL
                )
            """)
            self.conn.commit()

    def add_message(self, sender: str, content: str, recipient: str = None, ttl: int = None) -> str:
        msg_id = str(uuid.uuid4())
        timestamp = time.time()
        expires_at = timestamp + ttl if ttl else None
        encrypted_content = self.cipher.encrypt(content)
        with self.lock:
            # Use connection as context manager for automatic commit/rollback
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
        # Get last 'limit' messages that are not deleted and not expired
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

        # Decrypt outside of the lock to reduce lock contention
        decrypted_rows = []
        for row in rows:
            decrypted_content = self.cipher.decrypt(row[2])
            # Return 7 columns
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

        # Decrypt outside of the lock to reduce lock contention
        decrypted_rows = []
        for row in rows:
            decrypted_filename = self.cipher.decrypt(row[1])
            decrypted_path = self.cipher.decrypt(row[2])
            decrypted_rows.append((row[0], decrypted_filename, decrypted_path, row[3], row[4], row[5], row[6], row[7]))
        return decrypted_rows

    def is_file_shared(self, path: str) -> bool:
        """Check if a file path is currently shared and not expired."""
        now = time.time()
        with self.lock:
            # Fetch only the path column to reduce data transfer and decryption overhead
            cursor = self.conn.execute("SELECT path FROM files WHERE expires_at IS NULL OR expires_at > ?", (now,))
            rows = cursor.fetchall()

        # Check outside the lock; early exit when match is found
        for row in rows:
            decrypted_path = self.cipher.decrypt(row[0])
            if decrypted_path == path:
                return True
        return False

    def delete_expired_files(self) -> int:
        """Purge files that have passed their expiration time. Returns count of deleted files."""
        now = time.time()
        with self.lock:
            with self.conn:
                cursor = self.conn.execute("DELETE FROM files WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
                return cursor.rowcount

    def delete_expired_messages(self) -> int:
        """Purge messages that have passed their expiration time. Returns count of deleted messages."""
        now = time.time()
        with self.lock:
            with self.conn:
                cursor = self.conn.execute("DELETE FROM messages WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
                return cursor.rowcount

    def add_trusted_peer(self, ip: str, username: str, fingerprint: str, trust_level: str = 'untrusted'):
        now = time.time()
        with self.lock:
            with self.conn:
                # Use COALESCE to preserve existing permissions if they exist
                self.conn.execute("""
                    INSERT INTO trusted_peers (ip, username, fingerprint, trust_level, last_seen)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(ip) DO UPDATE SET
                        username=excluded.username,
                        fingerprint=excluded.fingerprint,
                        trust_level=COALESCE(trust_level, excluded.trust_level),
                        last_seen=excluded.last_seen
                """, (ip, username, fingerprint, trust_level, now))

    def get_trusted_peer(self, ip: str) -> Tuple:
        with self.lock:
            # Explicitly select columns to handle schema variations gracefully
            cursor = self.conn.execute("SELECT ip, username, fingerprint, trust_level, can_chat, can_list_files, can_download_files, is_blocked, last_seen FROM trusted_peers WHERE ip = ?", (ip,))
            return cursor.fetchone()

    def get_peer_permissions(self, ip: str) -> dict:
        """Get granular permissions for a peer."""
        # Normalize localhost to allow testing on a single machine
        if ip == "127.0.0.1":
            # For testing, we might want to check the specific entry,
            # but usually it's better to use the IP as is.
            pass
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

    def update_peer_permissions(self, ip: str, permissions_dict: dict):
        """Update granular permissions for a peer."""
        fields = []
        values = []
        for key in ['can_chat', 'can_list_files', 'can_download_files', 'is_blocked']:
            if key in permissions_dict:
                fields.append(f"{key} = ?")
                values.append(1 if permissions_dict[key] else 0)

        if not fields:
            return

        values.append(ip)
        query = f"UPDATE trusted_peers SET {', '.join(fields)} WHERE ip = ?"

        with self.lock:
            with self.conn:
                self.conn.execute("INSERT OR IGNORE INTO trusted_peers (ip) VALUES (?)", (ip,))
                self.conn.execute(query, tuple(values))

    def get_peer_trust_levels(self, ips: List[str]) -> dict:
        """Batch fetch trust levels for multiple IPs to reduce DB roundtrips."""
        ips_list = list(ips)
        if not ips_list:
            return {}
        placeholders = ",".join(["?"] * len(ips_list))
        with self.lock:
            cursor = self.conn.execute(f"SELECT ip, trust_level FROM trusted_peers WHERE ip IN ({placeholders})", ips_list)
            return {row[0]: row[1] for row in cursor.fetchall()}

    def update_peer_trust(self, ip: str, trust_level: str):
        with self.lock:
            with self.conn:
                self.conn.execute("UPDATE trusted_peers SET trust_level = ? WHERE ip = ?", (trust_level, ip))

    def add_audit_log(self, event_type: str, details: str):
        timestamp = time.time()
        with self.lock:
            with self.conn:
                self.conn.execute("INSERT INTO audit_logs (event_type, details, timestamp) VALUES (?, ?, ?)",
                                 (event_type, details, timestamp))

    def get_audit_logs(self, limit=100) -> List[Tuple]:
        with self.lock:
            cursor = self.conn.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT ?", (limit,))
            return cursor.fetchall()

    def reap_expired_messages(self) -> int:
        return self.delete_expired_messages()

    def close(self):
        self.conn.close()
