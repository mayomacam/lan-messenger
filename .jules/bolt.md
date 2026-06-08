## 2025-05-15 - [SQLite Performance Optimization]
**Learning:** SQLite default configurations (synchronous journaling, no indexes) can lead to significant bottlenecks as data grows. Enabling WAL mode and adding strategic indexes can improve performance by orders of magnitude (e.g., 40x faster retrieval, 4x faster insertion).
**Action:** Always check if core tables have indexes for fields used in `ORDER BY` or `WHERE` clauses. Enable WAL mode for applications with concurrent read/writes.
