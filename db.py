import sqlite3
import uuid
import time
import threading
import os
import base64
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
            # Messages table: id, sender, content, timestamp, is_deleted, recipient
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    content TEXT,
                    timestamp REAL NOT NULL,
                    is_deleted BOOLEAN DEFAULT 0,
                    recipient TEXT
                )
            """)
            # Migration: add recipient column if it doesn't exist
            cursor.execute("PRAGMA table_info(messages)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'recipient' not in columns:
                cursor.execute("ALTER TABLE messages ADD COLUMN recipient TEXT")

            # Optimized composite index for faster message retrieval by recipient, status, and timestamp
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_recipient_deleted_ts ON messages(recipient, is_deleted, timestamp)")
            # Drop old less efficient indexes
            cursor.execute("DROP INDEX IF EXISTS idx_messages_deleted_timestamp")
            cursor.execute("DROP INDEX IF EXISTS idx_messages_recipient")
            # Files table: id, filename, path, size, owner_ip, is_folder
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER,
                    owner_ip TEXT NOT NULL,
                    is_folder BOOLEAN DEFAULT 0
                )
            """)

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

    def add_message(self, sender: str, content: str, recipient: str = None) -> str:
        msg_id = str(uuid.uuid4())
        timestamp = time.time()
        encrypted_content = self.cipher.encrypt(content)
        with self.lock:
            # Use connection as context manager for automatic commit/rollback
            with self.conn:
                self.conn.execute("INSERT INTO messages (id, sender, content, timestamp, recipient) VALUES (?, ?, ?, ?, ?)",
                                 (msg_id, sender, encrypted_content, timestamp, recipient))
        return msg_id

    def add_received_message(self, msg_id: str, sender: str, content: str, timestamp: float, recipient: str = None):
        encrypted_content = self.cipher.encrypt(content)
        with self.lock:
            with self.conn:
                self.conn.execute("INSERT OR IGNORE INTO messages (id, sender, content, timestamp, recipient) VALUES (?, ?, ?, ?, ?)",
                                 (msg_id, sender, encrypted_content, timestamp, recipient))

    def get_messages(self, limit=50, peer_ip: str = None) -> List[Tuple]:
        # Get last 'limit' messages that are not deleted
        # If peer_ip is provided, get private messages involving peer_ip
        # (Both sent and received private messages are stored with recipient=peer_ip)
        # Otherwise get global messages (recipient IS NULL)
        with self.lock:
            if peer_ip:
                cursor = self.conn.execute("""
                    SELECT id, sender, content, timestamp, is_deleted, recipient
                    FROM messages
                    WHERE is_deleted = 0
                    AND recipient = ?
                    ORDER BY timestamp DESC LIMIT ?
                """, (peer_ip, limit))
            else:
                cursor = self.conn.execute("""
                    SELECT id, sender, content, timestamp, is_deleted, recipient
                    FROM messages
                    WHERE is_deleted = 0 AND recipient IS NULL
                    ORDER BY timestamp DESC LIMIT ?
                """, (limit,))

            rows = cursor.fetchall()
            decrypted_rows = []
            for row in rows:
                decrypted_content = self.cipher.decrypt(row[2])
                decrypted_rows.append((row[0], row[1], decrypted_content, row[3], row[4], row[5]))
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

    def add_file(self, filename: str, path: str, size: int, owner_ip: str, is_folder: bool = False) -> str:
        file_id = str(uuid.uuid4())
        with self.lock:
            with self.conn:
                self.conn.execute("INSERT INTO files (id, filename, path, size, owner_ip, is_folder) VALUES (?, ?, ?, ?, ?, ?)",
                                 (file_id, filename, path, size, owner_ip, is_folder))
        return file_id

    def get_files(self) -> List[Tuple]:
        with self.lock:
            cursor = self.conn.execute("SELECT * FROM files")
            return cursor.fetchall()

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

    def close(self):
        self.conn.close()
