## 2025-06-11 - SQLite Performance Optimization
**Learning:** Enabling Write-Ahead Logging (WAL) and setting synchronous to NORMAL in SQLite significantly improves concurrent write performance by reducing disk synchronization overhead and allowing simultaneous readers and writers. Additionally, indexing frequently ordered columns like 'timestamp' prevents full table scans during message retrieval.
**Action:** Always enable WAL mode and add indexes for columns used in ORDER BY or WHERE clauses for any SQLite database in high-concurrency or data-heavy applications.
