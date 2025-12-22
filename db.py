import sqlite3
import uuid
import time
from typing import List, Tuple

class Database:
    def __init__(self, db_name="lan_messenger.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        # Messages table: id, sender, content, timestamp, is_deleted
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                sender TEXT NOT NULL,
                content TEXT,
                timestamp REAL NOT NULL,
                is_deleted BOOLEAN DEFAULT 0
            )
        """)
        # Files table: id, filename, path, size, owner_ip, is_folder
        self.cursor.execute("""
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
        self.cursor.execute("INSERT INTO messages (id, sender, content, timestamp) VALUES (?, ?, ?, ?)",
                            (msg_id, sender, content, timestamp))
        self.conn.commit()
        return msg_id

    def get_messages(self, limit=50) -> List[Tuple]:
        # Get last 'limit' messages that are not deleted
        self.cursor.execute("SELECT * FROM messages WHERE is_deleted = 0 ORDER BY timestamp DESC LIMIT ?", (limit,))
        return self.cursor.fetchall()[::-1]

    def delete_message(self, msg_id: str):
        self.cursor.execute("UPDATE messages SET is_deleted = 1 WHERE id = ?", (msg_id,))
        self.conn.commit()

    def edit_message(self, msg_id: str, new_content: str):
        self.cursor.execute("UPDATE messages SET content = ? WHERE id = ?", (new_content, msg_id))
        self.conn.commit()
        
    def add_file(self, filename: str, path: str, size: int, owner_ip: str, is_folder: bool = False) -> str:
        file_id = str(uuid.uuid4())
        self.cursor.execute("INSERT INTO files (id, filename, path, size, owner_ip, is_folder) VALUES (?, ?, ?, ?, ?, ?)",
                            (file_id, filename, path, size, owner_ip, is_folder))
        self.conn.commit()
        return file_id

    def get_files(self) -> List[Tuple]:
        self.cursor.execute("SELECT * FROM files")
        return self.cursor.fetchall()

    def close(self):
        self.conn.close()
