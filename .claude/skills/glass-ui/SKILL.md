---
name: glass-ui
description: Default UI template for new programs, apps, tools, dashboards and screens — a Thai-language Glassmorphism (Liquid Glass) sidebar dashboard with frosted glass cards, pastel gradient blob background and automatic light/dark theme. Use whenever the user asks to build a new program, app, desktop tool, admin page, dashboard or any UI and does NOT specify a visual style, or when they mention "glass", "glassmorphism", "liquid glass", "เทมเพลตเดิม", "แบบ Epson", "หน้าตาแบบเดิม". Skip it when the user names a different style or design system.
---

# Glass UI (default template)

Ready-made HTML/CSS/JS shell: sidebar + topbar + pages, frosted-glass cards, line icons, toast and modal. Thai UI text by default.

## Steps

1. Copy `template/` (next to this file) into the new project's UI folder, e.g. `ui/`. Leave out `preview.jpg`.
2. Rename the app: `<title>`, `.brand-name`, `.brand-sub`; replace `logo.svg` (keep it square, works on light and dark).
3. Make the menu: one `<button class="nav-btn" data-page="x">` per page in `<nav>`, a matching `<section class="page" id="page-x">`, and an entry in `PAGES` in `app.js`.
4. Brand colours: change `--accent`, `--accent-2` and `--blob-1..4` in `style.css`, in BOTH the `:root` block and the `@media (prefers-color-scheme: dark)` block.
5. Build pages from the existing classes before writing new CSS. The component table is in [REFERENCE.md](REFERENCE.md); `template/index.html` shows each one in use.
6. Icons: add new `<symbol id="i-name">` to the sprite at the top of `index.html` (24×24 viewBox, `stroke-width="1.8"`, round caps/joins, `stroke="currentColor"`, no fill), use with `<svg><use href="#i-name"/></svg>`.
7. Delete Epson-only CSS you don't need (`.inks`, `.tube`, `.models`).

## Rules that keep the look

- Every surface that sits on the background gets `.glass` (cards, sidebar, topbar, tiles, tools).
- Layout uses `.grid.g-12` with `.span-*`; don't hand-roll widths.
- Keep the backdrop (`.backdrop` blobs + `.grain`) and `.shell` structure unchanged.
- Status colours only via `ok / warn / bad / info` modifiers (`.pill`, `.alert`, `.orb`, `.meter`).
- Numbers use `.num` (tabular figures). Big stats go in `.tile` with a `<small>` unit.
- Confirm destructive actions with `confirmBox(title, sub, okText, "bad")`; report results with `toast(text, "ok"|"bad"|"info")`.
- Light/dark is automatic — never hard-code colours outside the CSS variables.

## Desktop apps (Windows)

Open the page with pywebview and expose a Python class; JavaScript calls `await window.pywebview.api.method(...)` and gets a dict back. Wait for the `pywebviewready` event before the first call. Package with PyInstaller using `--add-data "ui;ui"`.

## Check before handing over

Open `index.html` in a browser (Playwright screenshot is fine) in both `colorScheme: 'light'` and `'dark'`, and at a narrow width, and make sure there are no console errors.
