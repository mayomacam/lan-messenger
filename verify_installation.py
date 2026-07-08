import os
import sys

def verify():
    print("Testing Database...")
    try:
        from db import Database
        # Clean up any existing test artifacts
        if os.path.exists("test_install.db"): os.remove("test_install.db")
        if os.path.exists(".test_install.key"): os.remove(".test_install.key")

        db = Database("test_password", db_name="test_install.db", key_file=".test_install.key")
        db.add_message("System", "Installation Verified")
        msgs = db.get_messages()
        if len(msgs) > 0 and msgs[0][1] == "System":
            print("Database OK")
        else:
            print("Database FAILED: Message retrieval error")

        db.close()
        if os.path.exists("test_install.db"): os.remove("test_install.db")
        if os.path.exists(".test_install.key"): os.remove(".test_install.key")
    except Exception as e:
        print(f"Database FAILED: {e}")

    print("Testing Imports...")
    try:
        import customtkinter
        import cryptography
        import PIL
        print("Imports OK")
    except ImportError as e:
        print(f"Imports FAILED: {e}")

if __name__ == "__main__":
    verify()
