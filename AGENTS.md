# Aura contributor contract

Aura is an independent third-party Luma app. Do not add it to Luma core packages or OS composition.

- Use existing Luma AppKit/LumaUI components and tokens for native UI. Structural chrome is platform-owned; wallpaper pixels and monitor diagrams are app content.
- Keep one responsive GTK implementation. Preserve every action at 360 pixels, including a live preview when adjusting controls.
- Never export an enlarged preview. Evaluate recipes at output resolution with bounded working memory; preserve deterministic per-monitor coordinates and atomic replacement.
- Keep preview work coalesced and nonblocking. No idle polling, resident service, telemetry or unexpected network calls.
- Preserve local designs and export history across upgrades. Cancellation must not remove an existing destination or completed batch files.
- Run meaningful engine tests after renderer/data changes, and native runtime/visual tests after UI changes. Record only observed results in docs/verification.md.
- Keep generated exports, build trees, user data and credentials out of Git. No DCO signoff or public licensing decision on the owner's behalf.

- Keep operational handoffs, conversation excerpts, account/device details and
  server logs outside version control. Use the environment's task registry for
  private coordination. Public docs describe app behavior, development and
  observed qualification only.
