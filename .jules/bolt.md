## 2025-05-15 - [SQLite Performance Optimization]
**Learning:** SQLite default configurations (synchronous journaling, no indexes) can lead to significant bottlenecks as data grows. Enabling WAL mode and adding strategic indexes can improve performance by orders of magnitude (e.g., 40x faster retrieval, 4x faster insertion).
**Action:** Always check if core tables have indexes for fields used in `ORDER BY` or `WHERE` clauses. Enable WAL mode for applications with concurrent read/writes.

## 2025-05-16 - [SSL Context Creation Overhead]
**Learning:** `ssl.create_default_context()` and `load_cert_chain()` are surprisingly expensive (~1.5ms to 2.2ms per call) because they involve parsing certificates and initializing the OpenSSL engine. In a high-frequency connection environment (like P2P chat), this adds up.
**Action:** Cache `ssl.SSLContext` objects for reuse across connections. Centralize SSL management in a utility module to ensure consistent caching and security settings.
