from db import Database
import os

db_name = "test_verify.db"
if os.path.exists(db_name):
    os.remove(db_name)

db = Database(db_name=db_name)
cursor = db.conn.cursor()
cursor.execute("PRAGMA table_info(trusted_peers)")
columns = {info[1]: info for info in cursor.fetchall()}

expected_columns = ['can_chat', 'can_list_files', 'can_download_files', 'is_blocked']
for col in expected_columns:
    if col in columns:
        print(f"Column {col} found: {columns[col]}")
    else:
        print(f"Column {col} MISSING!")

# Test add and retrieve permissions
ip = "127.0.0.1"
db.add_trusted_peer(ip, "Tester", "fingerprint123")
perms = db.get_peer_permissions(ip)
print(f"Default permissions for {ip}: {perms}")

db.update_peer_permissions(ip, {'can_chat': False, 'is_blocked': True})
perms_updated = db.get_peer_permissions(ip)
print(f"Updated permissions for {ip}: {perms_updated}")

db.close()
os.remove(db_name)
