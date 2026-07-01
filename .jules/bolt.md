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

## 2025-05-21 - [Linear-time Data Collection & UI Batching]
**Learning:** Python's iterative bytes concatenation is O(n²) because bytes are immutable, leading to significant slowdowns in network recv loops. Additionally, individual 'insert' calls to Tkinter Text widgets trigger expensive layout recalculations for every line.
**Action:** Use 'b"".join(chunks)' for socket data accumulation and join strings with "\n" for single-call UI text insertions to achieve O(n) and O(1) performance respectively.

## 2025-05-22 - [Lock Contention and DB Batching]
**Learning:** Holding a database lock while performing CPU-intensive tasks like AES decryption blocks all other database operations, including writes from network threads. Additionally, performing multiple individual lookups in a loop (O(N)) is significantly slower than a single batch query (O(1)) due to repeated lock acquisition and SQL execution overhead.
**Action:** Move CPU-bound post-processing outside of database locks and implement batch lookup methods (e.g., using SQL 'IN' clauses) to minimize lock contention and improve overall throughput.

## 2025-05-23 - [LRU Caching and Selective Data Fetching]
**Learning:** Repetitive decryption of identical ciphertexts (common in chat history) and fetching entire rows just to check a single field are major performance sinks. LRU caching for decryption and selective SQL column fetching can reduce execution time by 40-90%.
**Action:** Use functools.lru_cache for expensive idempotent operations like decryption. Always fetch only the minimum required columns for validation checks to minimize data transfer and processing overhead.

## 2025-05-24 - [UI Refresh Cycles with Debouncing and Lazy Loading]
**Learning:** Polling loops and unconditioned UI updates (e.g., refreshing all chat tabs when only one is visible) are major performance sinks in GUI apps. Implementing visibility checks (lazy loading) and debouncing (throttling) ensures that CPU-intensive rendering and database queries only occur when necessary.
**Action:** Always check widget visibility or tab state before performing heavy UI updates. Use a standard debounce pattern (e.g., 100ms) for high-frequency events to prevent UI lag.

## 2026-07-01 - [Thread-Safe DB Caching & Batching]
**Learning:** Using `lru_cache` on methods returning mutable objects (like dicts) can lead to accidental cache pollution if callers modify the results. Additionally, clearing the cache outside of a mutex can cause race conditions where a reader caches stale data from the DB before the writer completes.
**Action:** Always cache immutable types (tuples) in internal helpers and convert to mutable types (dicts) in public wrappers. Ensure `cache_clear()` is called *inside* the same lock used for database writes to maintain strict consistency. Use SQL 'IN' clauses for batch permission fetching to eliminate O(N) query patterns in UI loops.
