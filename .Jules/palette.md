## 2026-06-04 - [Code Redundancy and UX Consistency]
**Learning:** Redundant method definitions in UI code (likely from merge conflicts or poor version control) can lead to inconsistent behavior and "zombie" features that don't update correctly. In this app, update_username, refresh_peers, open_settings, and on_closing were duplicated, causing confusion.
**Action:** Always scan for duplicate method names when working on UI files to ensure UX consistency and maintainability.

## 2025-05-20 - Global hotkeys and dialog accessibility
**Learning:** Adding standard global hotkeys like <Control-f> for search and ensuring all modal dialogs are dismissible via the <Escape> key significantly improves the efficiency for power users and keyboard accessibility.
**Action:** Always include a global search shortcut and bind <Escape> to 'destroy' in all CTkToplevel dialogs.
