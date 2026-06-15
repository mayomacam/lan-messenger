## 2025-05-15 - Improving interface intuition with descriptive labels
**Learning:** Cryptic icons like "✓" can be confusing for users. Replacing them with descriptive labels like "Set" significantly improves the immediate understanding of the button's action.
**Action:** Always prefer clear, descriptive text over icon-only buttons, especially for primary actions.

## 2025-05-15 - Navigational aids in complex views
**Learning:** When users browse remote content (like peer files), they can feel "lost" without an easy way to return to their own local view.
**Action:** Provide explicit navigation buttons (e.g., "My Files") to return to the application's default state.

## 2026-06-10 - Facilitating peer-to-peer data exchange
**Learning:** In P2P applications, essential connection info (like local IP) should be as accessible as possible. Providing a one-click "Copy" button next to the IP address reduces user friction and potential transcription errors.
**Action:** Include convenient "Copy" buttons for critical connection metadata and ensure dialog inputs are automatically focused for immediate use.

## 2026-06-12 - Enhancing workflow through focus management and guidance
**Learning:** Automatically focusing input fields on view transitions (like app start or tab switches) and providing keyboard-driven actions (like Enter to save) reduces cognitive load and physical effort for users. Additionally, "empty states" in dynamic lists prevent confusion by confirming the app is working even when no data is present.
**Action:** Always identify primary input fields in every view/dialog and ensure they are focused automatically. Include helpful "empty state" labels for all dynamic collections.

## 2026-06-13 - Context-aware focus and non-blocking feedback
**Learning:** In multi-tabbed chat interfaces, focus should be maintained on the relevant input field when switching between conversations to ensure a seamless typing experience. Furthermore, using the button itself to provide success feedback (e.g., "Refreshed") for background refreshes provides a clean, modern alternative to intrusive popups.
**Action:** Always map tab selections to their corresponding input widgets for automatic focusing. Use temporary button label/color shifts for non-disruptive interaction confirmation.

## 2026-06-15 - Live search and automated data refresh
**Learning:** Live search with debounce provides immediate feedback and feels significantly more modern than manual "Search" buttons. Automated data fetching upon tab transitions (e.g., refreshing logs when the tab is selected) eliminates redundant user actions and ensures the UI always displays current state. Furthermore, "empty states" should extend to search results to confirm that the absence of data is due to filtering rather than a failure.
**Action:** Implement 300ms debounce for all live-search fields. Use tab-change events to trigger background data refreshes for secondary views like logs or stats. Always provide explicit "No results found" placeholders for filtered views.
