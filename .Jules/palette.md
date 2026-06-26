## 2026-06-04 - [Code Redundancy and UX Consistency]
**Learning:** Redundant method definitions in UI code (likely from merge conflicts or poor version control) can lead to inconsistent behavior and "zombie" features that don't update correctly. In this app, update_username, refresh_peers, open_settings, and on_closing were duplicated, causing confusion.
**Action:** Always scan for duplicate method names when working on UI files to ensure UX consistency and maintainability.

## 2026-06-26 - [Visual Scannability in Logs]
**Learning:** Users can process semantic colors (red/orange/green) significantly faster than plain text labels for identifying critical events in dense logs. Standardizing event-to-color mapping across the app (alert/warning/info) creates a cohesive mental model.
**Action:** Always implement semantic tagging for data-heavy displays like audit logs or system notifications to reduce cognitive load.
