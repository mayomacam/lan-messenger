
import os
import shutil
import time
from db import Database

def verify_ui_lock_logic():
    db_file = "test_verify.db"
    if os.path.exists(db_file): os.remove(db_file)
    if os.path.exists(".master.key"): os.remove(".master.key")

    db = Database(db_file)

    print("Step 1: Check initial state")
    assert db.needs_setup() == True
    assert db.is_locked() == True

    print("Step 2: Setup password")
    password = "test_password"
    db.setup(password)
    assert db.needs_setup() == False
    assert db.is_locked() == False

    print("Step 3: Test locking")
    db.lock_db()
    assert db.is_locked() == True

    print("Step 4: Test unlocking with wrong password")
    assert db.unlock("wrong") == False
    assert db.is_locked() == True

    print("Step 5: Test unlocking with correct password")
    assert db.unlock(password) == True
    assert db.is_locked() == False

    db.close()
    if os.path.exists(db_file): os.remove(db_file)
    if os.path.exists(".master.key"): os.remove(".master.key")
    print("VERIFICATION SUCCESSFUL")

if __name__ == "__main__":
    verify_ui_lock_logic()
