import threading
import time
from db import Database
import os

def test_concurrency():
    # Use a test database
    db_name = "test_stress.db"
    if os.path.exists(db_name):
        os.remove(db_name)
        
    db = Database(db_name)
    
    def worker(name):
        for i in range(50):
            msg_id = db.add_message(name, f"Message {i} from {name}")
            db.get_messages(10)
            db.edit_message(msg_id, f"Edited {i} by {name}")
            time.sleep(0.01)
            
    threads = []
    for i in range(10):
        t = threading.Thread(target=worker, args=(f"Thread-{i}",))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    messages = db.get_messages(1000)
    print(f"Total messages in DB: {len(messages)}")
    db.close()
    if os.path.exists(db_name):
        os.remove(db_name)
    
    # If no crashes occurred, the lock is working.
    assert len(messages) == 500
    print("Test PASSED: No crashes and all messages saved.")

if __name__ == "__main__":
    test_concurrency()
