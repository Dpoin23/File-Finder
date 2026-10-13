# Desktop launcher

The desktop surface is a launcher popup on a local background process. Search behavior, indexing, and rank order are in [DESIGN.md](DESIGN.md). This file covers only the app.

## Form

The visible app is a launcher, in the style of a system search popup. It is a real local process, because the index and the files live on disk. It is not a multi-page application, and it is not a browser extension.

`ff ui` opens the window. `ff init`, `ff index`, and `ff query` stay terminal commands. The window reads the roots and the catalog those commands wrote, and a search calls the same function as `ff query`. The list shows the path, the matching chunk, and which lane produced the hit. A side panel shows the path as segments and a tree of those hits under their roots. Enter opens the file in `FF_EDITOR`, `VISUAL`, `EDITOR`, or the default application. Escape closes the window.

A global hotkey and a tray icon are not part of this command. The tray would show whether the index is current and could trigger a refresh. The window does not walk the tree or embed anything.

## Why this shape

The search has to be available from the editor, the terminal, and the file manager, not only from a browser tab. A browser extension cannot freely read local folders or register a system-wide hotkey. Doing either requires a native companion, which is this process.

Skip a full windowed app with settings pages, history, and navigation until the popup is in daily use. Settings can live in the config file until then.

## Later clients

Two later clients can sit on the same process when a specific scenario shows up. They are not the first interface.

| Scenario | Surface |
| --- | --- |
| Find a file while in any app | Launcher popup. This is the default. |
| Already in the editor, search the open workspace | Editor extension that calls the local query. |
| On a GitHub page for a repo that is cloned locally | Browser extension that can reveal or open the local file. Still needs the local process. |
