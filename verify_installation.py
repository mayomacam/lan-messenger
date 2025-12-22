import sys
import os
import time
import threading

# Add current dir to path
sys.path.append(os.getcwd())

def test_db():
    print("Testing Database...")
    try:
        from db import Database
        db = Database("test.db")
        msg_id = db.add_message("test_user", "hello")
        msgs = db.get_messages()
        assert len(msgs) > 0
        assert msgs[0][2] == "hello"
        db.close()
        try:
            os.remove("test.db")
        except:
             pass
        print("Database OK")
    except Exception as e:
        print(f"Database FAILED: {e}")

def test_imports():
    print("Testing Imports...")
    try:
        import customtkinter
        import network
        import file_transfer
        import ui
        print("Imports OK")
    except ImportError as e:
        print(f"Imports FAILED: {e}")
    except Exception as e:
        # ui might fail due to no display
        if "display" in str(e).lower() or "screen" in str(e).lower():
            print("UI Import attempted (Display error expected in headless):", e)
        else:
            print(f"Import FAILED with unknown error: {e}")

if __name__ == "__main__":
    test_db()
    test_imports()
