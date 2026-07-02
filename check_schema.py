import sqlite3
import os
from db import Database

db_name = "test_verify_schema.db"
key_file = ".test_master_schema.key"
if os.path.exists(db_name):
    os.remove(db_name)
if os.path.exists(key_file):
    os.remove(key_file)

try:
    db = Database("password", db_name=db_name, key_file=key_file)

    conn = sqlite3.connect(db_name)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(trusted_peers)")
    columns = [row[1] for row in cursor.fetchall()]
    print(f"Columns in trusted_peers: {columns}")

    if "is_verified" in columns:
        print("SUCCESS: is_verified column found.")
    else:
        print("FAILURE: is_verified column NOT found.")

    conn.close()
finally:
    if os.path.exists(db_name):
        os.remove(db_name)
    if os.path.exists(key_file):
        os.remove(key_file)
