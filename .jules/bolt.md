## 2025-05-14 - Initial Performance Audit
**Learning:** The database uses a global threading lock in `db.py` for all operations. While safe, it causes significant contention under load. SQLite's WAL mode and better transaction management could improve concurrency.
**Action:** Implement SQLite WAL mode and use context managers for better transaction handling.
