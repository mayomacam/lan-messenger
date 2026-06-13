## 2025-05-15 - [SQLite Performance Optimization]
**Learning:** SQLite default configurations (synchronous journaling, no indexes) can lead to significant bottlenecks as data grows. Enabling WAL mode and adding strategic indexes can improve performance by orders of magnitude (e.g., 40x faster retrieval, 4x faster insertion).
**Action:** Always check if core tables have indexes for fields used in `ORDER BY` or `WHERE` clauses. Enable WAL mode for applications with concurrent read/writes.

## 2025-05-16 - [SSL Context Creation Overhead]
**Learning:** `ssl.create_default_context()` and `load_cert_chain()` are surprisingly expensive (~1.5ms to 2.2ms per call) because they involve parsing certificates and initializing the OpenSSL engine. In a high-frequency connection environment (like P2P chat), this adds up.
**Action:** Cache `ssl.SSLContext` objects for reuse across connections. Centralize SSL management in a utility module to ensure consistent caching and security settings.

## 2025-05-17 - [Efficient Socket Data Collection]
**Learning:** Iterative byte string concatenation (e.g., `data += chunk`) in Python is an O(n^2) operation because strings/bytes are immutable, leading to massive performance degradation as the data size grows (e.g., 50MB taking >150s vs <0.1s).
**Action:** Always collect data chunks in a list and use `b"".join(chunks)` for linear time complexity. Pair this with a larger 64KB buffer to minimize syscall overhead.

## 2025-05-18 - [Tkinter Widget Churn & Batching]
**Learning:** Rebuilding complex widget hierarchies in a loop (e.g., `self.after` every 2s) and performing individual `insert` calls into text widgets are hidden performance killers in Tkinter. Snapshot-based change detection and batched string insertions minimize layout engine thrashing and rendering latency.
**Action:** Use snapshot comparison to skip redundant UI updates and batch text insertions using `"\n".join(lines)` for a single `insert` call.

## 2025-05-19 - [UI Polling and Text Batching]
**Learning:** Polling loops that rebuild the entire UI every few seconds are a major source of layout thrashing and CPU waste in Tkinter. Snapshot-based comparison allows skipping 99% of these updates. Similarly, inserting text line-by-line into a Textbox widget is O(N) in terms of layout recalculations; batching into a single string makes it O(1).
**Action:** Use self._last_peers_snapshot for periodic UI refreshes and always batch string insertions into Text/Textbox widgets using "\n".join(lines).

## 2025-05-20 - [Strategic Composite Indexes]
**Learning:** Separate indexes on individual columns often fail to optimize queries with multiple `WHERE` clauses and an `ORDER BY` clause. Following the ESR (Equality, Sort, Range) rule by creating a composite index (e.g., `(recipient, is_deleted, timestamp)`) allows SQLite to satisfy the entire query via a single index scan, providing a ~100x speedup in retrieval.
**Action:** Analyze query plans with `EXPLAIN QUERY PLAN` and prefer composite indexes that match the filtering and sorting requirements of the application's most frequent queries.
