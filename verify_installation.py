
import sys
import os
from db import Database

def test_db():
    print("Testing Database...")
    db_file = "test_verify_install.db"
    if os.path.exists(db_file): os.remove(db_file)
    if os.path.exists(".master.key"): os.remove(".master.key")

    try:
        db = Database(db_file)
        db.setup("test_password")
        msg_id = db.add_message("System", "Verification test message")
        if msg_id:
            print("Database OK")
        else:
            print("Database FAILED: No msg_id returned")
        db.close()
    except Exception as e:
        print(f"Database FAILED: {e}")
    finally:
        if os.path.exists(db_file): os.remove(db_file)
        if os.path.exists(".master.key"): os.remove(".master.key")

def test_imports():
    print("Testing Imports...")
    try:
        import customtkinter
        import cryptography
        import PIL
        print("Imports OK")
    except ImportError as e:
        print(f"Import FAILED: {e}")

if __name__ == "__main__":
    test_imports()
    test_db()
