## 2025-05-15 - [SQLite WAL & Indexing]
**Learning:** Enabling WAL (Write-Ahead Logging) mode and setting synchronous to NORMAL in SQLite provides a massive performance boost for concurrent write-heavy workloads (from ~3.9s to ~0.3s for 3000 operations in this app). Additionally, explicit indexing on frequently sorted columns (like 'timestamp' for messages) is critical as the database grows.
**Action:** Always check default SQLite PRAGMAs in peer-to-peer apps where local DB performance directly impacts UI responsiveness.
