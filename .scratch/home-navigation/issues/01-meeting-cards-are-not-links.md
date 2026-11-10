# 01 - Meeting cards on the Home page are not links

**Source:** reported by the user on 2026-11-08 while opening several interview Meetings
for review.

**What to fix:** Middle-click (and Ctrl+click, or "Open in new tab" from the context
menu) on a Meeting in the Home page does nothing. The user cannot open several Meetings
in their own tabs.

**Cause:** the Home page navigates with `onClick={() => navigate(...)}` on elements that
are not anchors, so the browser has no `href` to open:

- `frontend/src/pages/HomePage.tsx:243`: the Meeting card is a `<div onClick>`;
- `frontend/src/pages/HomePage.tsx:171` and `:180`: the search-result title and each
  matching Segment are `<button onClick>`.

**Fix direction:** render these as React Router `<Link to={`/meetings/${id}`}>`, keeping
the current styling. The card also holds inline controls (rename field, actions), so
clicks on those must not follow the link. Stop propagation on them, or keep the link on
the title/body area only.

**Blocked by:** None. You can start now.

**Status:** done

**Acceptance criteria:**
- [x] Middle-click and Ctrl+click on a Meeting card open that Meeting in a new tab
- [x] The same holds for a search-result title and its Segment rows
- [x] A plain left click still navigates in the same tab
- [x] Renaming and the card's action buttons still work without navigating
- [x] A frontend test (`npm test`) asserts the card and search results render anchors with the Meeting's `href`
