## 2025-05-15 - Micro-UX: Descriptive Labels over Cryptic Icons
**Learning:** Icon-only buttons (like "✓") can be ambiguous and less accessible than clear descriptive text (like "Set"). Replacing them improves clarity with minimal code change.
**Action:** Prioritize text labels or ARIA labels for all interactive elements, especially those that trigger critical actions like setting a username.

## 2025-05-15 - Technical: Byte-level Editing for UTF-8 and CRLF
**Learning:** Using standard tools like `sed` or `replace_with_git_merge_diff` on files with UTF-8 characters (e.g., "✓") and CRLF line endings can lead to search failures or corruption.
**Action:** Use Python scripts for binary-safe search-and-replace to ensure character encoding and line endings are preserved correctly.
