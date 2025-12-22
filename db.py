import sqlite3
import uuid
import time
import threading
from typing import List, Tuple

class Database:
    def __init__(self, db_name="lan_messenger.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.lock = threading.Lock()
        self.create_tables()

    def create_tables(self):
        with self.lock:
            cursor = self.conn.cursor()
            # Messages table: id, sender, content, timestamp, is_deleted
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    sender TEXT NOT NULL,
                    content TEXT,
                    timestamp REAL NOT NULL,
                    is_deleted BOOLEAN DEFAULT 0
                )
            """)
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
            self.conn.commit()

    def add_message(self, sender: str, content: str) -> str:
        msg_id = str(uuid.uuid4())
        timestamp = time.time()
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("INSERT INTO messages (id, sender, content, timestamp) VALUES (?, ?, ?, ?)",
                                (msg_id, sender, content, timestamp))
            self.conn.commit()
        return msg_id

    def add_received_message(self, msg_id: str, sender: str, content: str, timestamp: float):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO messages (id, sender, content, timestamp) VALUES (?, ?, ?, ?)",
                                (msg_id, sender, content, timestamp))
            self.conn.commit()

    def get_messages(self, limit=50) -> List[Tuple]:
        # Get last 'limit' messages that are not deleted
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM messages WHERE is_deleted = 0 ORDER BY timestamp DESC LIMIT ?", (limit,))
            return cursor.fetchall()[::-1]

    def delete_message(self, msg_id: str):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE messages SET is_deleted = 1 WHERE id = ?", (msg_id,))
            self.conn.commit()

    def edit_message(self, msg_id: str, new_content: str):
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("UPDATE messages SET content = ? WHERE id = ?", (new_content, msg_id))
            self.conn.commit()
        
    def add_file(self, filename: str, path: str, size: int, owner_ip: str, is_folder: bool = False) -> str:
        file_id = str(uuid.uuid4())
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("INSERT INTO files (id, filename, path, size, owner_ip, is_folder) VALUES (?, ?, ?, ?, ?, ?)",
                                (file_id, filename, path, size, owner_ip, is_folder))
            self.conn.commit()
        return file_id

    def get_files(self) -> List[Tuple]:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM files")
            return cursor.fetchall()

    def close(self):
        self.conn.close()
