# Desktop launcher

The desktop surface is a launcher popup on a local background process. Search behavior, indexing, and rank order are in [DESIGN.md](DESIGN.md). This file covers only the app.

## Form

The visible app is a launcher, in the style of a system search popup. It is a real local process, because the index and the files live on disk. It is not a multi-page application, and it is not a browser extension.

A global hotkey opens one small window from any program. The user types a filename fragment or a description of the contents. The list shows a few results: path, matching chunk, and which root it came from. Enter opens the file in the default editor. Escape closes the window. A tray icon shows whether the index is current and can trigger a refresh.

The window calls the same query function as the CLI. It does not walk the tree or embed anything itself. Build it after phase 1, when a result has a chunk worth reading.

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
