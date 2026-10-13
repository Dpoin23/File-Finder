"""Window onto the existing commands. `ff init`, `ff index`, and `ff query` are unchanged."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from filefinder.text import classify
from filefinder.ui_view import HitView, SearchView, catalog_summary, execute_search, open_argv

try:
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import ttk
except ImportError:  # pragma: no cover - exercised only when python3-tk is absent
    tk = None
    ttk = None
    tkfont = None


_BG = "#12141a"
_PANEL = "#181b24"
_CARD = "#1e2230"
_CARD_ON = "#2a3348"
_LINE = "#2c3140"
_TEXT = "#e7e9ee"
_MUTED = "#8b93a7"
_FAINT = "#5c657a"
_ACCENT = "#8eb6ff"
_ENTRY = "#0e1016"
_WARN = "#e6c07b"

_LANE_ON = {
    "path": ("#1c3328", "#9ece6a"),
    "content": ("#3a3218", "#e6c07b"),
    "vector": ("#2c2440", "#c4a7e7"),
    "ripgrep": ("#3a261f", "#f0997b"),
}


class _EmbedderSlot:
    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir
        self.embedder = None
        self.error: str | None = None
        self.ready = False
        self._lock = threading.Lock()

    def resolve(self):
        with self._lock:
            if self.ready:
                return self.embedder, self.error
            try:
                from filefinder.embed import load_embedder

                self.embedder = load_embedder(self.config_dir, local_files_only=True)
            except Exception as exc:
                self.error = str(exc)
            self.ready = True
            return self.embedder, self.error


def run_ui(config_dir: Path, *, limit: int = 20, explain: bool = False) -> int:
    if tk is None:
        print("ff ui needs tkinter. On Debian/Ubuntu: sudo apt install python3-tk", file=sys.stderr)
        return 1
    try:
        window = Launcher(config_dir, limit=limit, explain=explain)
    except tk.TclError as exc:
        print(f"Could not open a window: {exc}", file=sys.stderr)
        return 1
    window.mainloop()
    return 0


_Window = tk.Tk if tk is not None else object


class Launcher(_Window):
    def __init__(self, config_dir: Path, *, limit: int, explain: bool) -> None:
        super().__init__()
        self.config_dir = config_dir
        self.limit = limit
        self._slot = _EmbedderSlot(config_dir)
        self._generation = 0
        self._after_id: str | None = None
        self._view = SearchView.blank()
        self._selected = 0
        self._cards: list[tk.Frame] = []
        self._snippets: list[tk.Label] = []
        self._path_iids: dict[str, str] = {}
        self._iid_paths: dict[str, str] = {}
        self._syncing = False
        self._font = _pick_font()

        self.title("File Finder")
        self.configure(bg=_BG)
        self.minsize(760, 480)
        self._style_tree()
        self._build(explain)
        self._place()
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", self._open_selected)
        self.bind("<Up>", self._move(-1))
        self.bind("<Down>", self._move(1))
        self.bind("<Control-c>", self._copy_path)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.after(30, self._focus_entry)

    def _build(self, explain: bool) -> None:
        self.grid_columnconfigure(0, weight=3, minsize=420)
        self.grid_columnconfigure(1, weight=2, minsize=280)
        self.grid_rowconfigure(2, weight=1)

        header = tk.Frame(self, bg=_BG)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(14, 8))
        header.grid_columnconfigure(0, weight=1)

        tk.Label(
            header,
            text="File Finder",
            bg=_BG,
            fg=_TEXT,
            font=(self._font, 13, "bold"),
        ).grid(row=0, column=0, sticky="w")

        self.explain_var = tk.BooleanVar(value=explain)
        explain_box = tk.Checkbutton(
            header,
            text="Explain",
            variable=self.explain_var,
            command=self._kick,
            bg=_BG,
            fg=_MUTED,
            activebackground=_BG,
            activeforeground=_TEXT,
            selectcolor=_ENTRY,
            highlightthickness=0,
            font=(self._font, 10),
        )
        explain_box.grid(row=0, column=1, sticky="e")

        border = tk.Frame(header, bg=_ACCENT, padx=1, pady=1)
        border.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.query_var = tk.StringVar()
        self.query_var.trace_add("write", self._on_query_changed)
        self.entry = tk.Entry(
            border,
            textvariable=self.query_var,
            bg=_ENTRY,
            fg=_TEXT,
            insertbackground=_TEXT,
            relief="flat",
            highlightthickness=0,
            font=(self._font, 15),
        )
        self.entry.pack(fill="x", ipady=8, padx=10)

        meta = tk.Frame(header, bg=_BG)
        meta.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.kind_label = tk.Label(meta, text="Search", bg=_BG, fg=_FAINT, font=(self._font, 10, "bold"))
        self.kind_label.pack(side="left")
        self.lane_row = tk.Frame(meta, bg=_BG)
        self.lane_row.pack(side="left", padx=(10, 0))
        self._paint_lanes(SearchView.blank())

        self.sentence = tk.Label(
            self,
            text="",
            bg=_BG,
            fg=_MUTED,
            font=(self._font, 10),
            wraplength=820,
            justify="left",
            anchor="w",
        )
        self.sentence.grid(row=1, column=0, columnspan=2, sticky="ew", padx=16)
        self.sentence.grid_remove()

        results_wrap = tk.Frame(self, bg=_PANEL, highlightbackground=_LINE, highlightthickness=1)
        results_wrap.grid(row=2, column=0, sticky="nsew", padx=(16, 8), pady=(8, 8))
        results_wrap.grid_rowconfigure(1, weight=1)
        results_wrap.grid_columnconfigure(0, weight=1)
        tk.Label(
            results_wrap,
            text="Results",
            bg=_PANEL,
            fg=_FAINT,
            font=(self._font, 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))

        self.canvas = tk.Canvas(results_wrap, bg=_PANEL, highlightthickness=0, bd=0, width=480)
        self.canvas.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(results_wrap, orient="vertical", command=self.canvas.yview, style="FF.Vertical.TScrollbar")
        scroll.grid(row=1, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scroll.set)
        self.result_box = tk.Frame(self.canvas, bg=_PANEL)
        self._window_id = self.canvas.create_window((0, 0), window=self.result_box, anchor="nw")
        self.result_box.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self._stretch_results)
        for widget in (self.canvas, self.result_box):
            self._bind_wheel(widget)
        self._show_prompt("Type a filename, or a sentence about what the file contains.")

        detail = tk.Frame(self, bg=_PANEL, highlightbackground=_LINE, highlightthickness=1)
        detail.grid(row=2, column=1, sticky="nsew", padx=(8, 16), pady=(8, 8))
        detail.grid_columnconfigure(0, weight=1)
        detail.grid_rowconfigure(5, weight=1)

        tk.Label(detail, text="Path", bg=_PANEL, fg=_FAINT, font=(self._font, 9, "bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=12, pady=(10, 4)
        )
        self.crumb_row = tk.Frame(detail, bg=_PANEL)
        self.crumb_row.grid(row=1, column=0, sticky="ew", padx=12)
        self.full_path = tk.Label(
            detail,
            text="",
            bg=_PANEL,
            fg=_MUTED,
            font=(self._font, 9),
            anchor="w",
            justify="left",
            wraplength=280,
        )
        self.full_path.grid(row=2, column=0, sticky="ew", padx=12, pady=(4, 8))

        tk.Label(detail, text="Match", bg=_PANEL, fg=_FAINT, font=(self._font, 9, "bold"), anchor="w").grid(
            row=3, column=0, sticky="ew", padx=12
        )
        self.match = tk.Text(
            detail,
            height=5,
            width=24,
            bg=_ENTRY,
            fg=_TEXT,
            relief="flat",
            highlightthickness=0,
            wrap="word",
            font=(self._font, 10),
            padx=8,
            pady=8,
        )
        self.match.grid(row=4, column=0, sticky="ew", padx=12, pady=(4, 8))
        self.match.configure(state="disabled")

        tree_head = tk.Frame(detail, bg=_PANEL)
        tree_head.grid(row=5, column=0, sticky="nsew", padx=12, pady=(0, 12))
        tree_head.grid_columnconfigure(0, weight=1)
        tree_head.grid_rowconfigure(1, weight=1)
        tk.Label(
            tree_head,
            text="Search tree",
            bg=_PANEL,
            fg=_FAINT,
            font=(self._font, 9, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self.tree = ttk.Treeview(tree_head, show="tree", selectmode="browse", style="FF.Treeview")
        self.tree.column("#0", width=180, minwidth=80, stretch=True)
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.tree.tag_configure("dir", foreground=_MUTED)
        self.tree.tag_configure("file", foreground=_TEXT)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-Button-1>", self._open_tree)

        footer = tk.Frame(self, bg=_BG)
        footer.grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 12))
        footer.grid_columnconfigure(1, weight=1)
        tk.Label(
            footer,
            text="↑↓ move   Enter open   Esc close",
            bg=_BG,
            fg=_FAINT,
            font=(self._font, 9),
        ).grid(row=0, column=0, sticky="w")
        self.status = tk.Label(footer, text="", bg=_BG, fg=_MUTED, font=(self._font, 9))
        self.status.grid(row=0, column=1, sticky="e")
        self.catalog = tk.Label(
            footer,
            text=catalog_summary(self.config_dir),
            bg=_BG,
            fg=_FAINT,
            font=(self._font, 9),
            anchor="w",
        )
        self.catalog.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        detail.bind("<Configure>", self._rewrap_path)

    def _place(self) -> None:
        self.update_idletasks()
        width, height = 920, 600
        x = max(0, (self.winfo_screenwidth() - width) // 2)
        y = max(0, (self.winfo_screenheight() - height) // 5)
        self.geometry(f"{width}x{height}+{x}+{y}")
        try:
            self.attributes("-topmost", True)
        except tk.TclError:
            pass

    def _focus_entry(self) -> None:
        self.entry.focus_set()

    def _style_tree(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "FF.Treeview",
            background=_PANEL,
            fieldbackground=_PANEL,
            foreground=_TEXT,
            borderwidth=0,
            relief="flat",
            rowheight=22,
            font=(self._font, 10),
        )
        style.map("FF.Treeview", background=[("selected", _CARD_ON)], foreground=[("selected", _TEXT)])
        style.layout("FF.Treeview", [("FF.Treeview.treearea", {"sticky": "nswe"})])
        style.configure(
            "FF.Vertical.TScrollbar",
            background=_LINE,
            troughcolor=_PANEL,
            borderwidth=0,
            arrowsize=12,
        )

    def _on_query_changed(self, *_args) -> None:
        text = self.query_var.get().strip()
        if text:
            self.kind_label.configure(text=_kind_label(classify(text)).upper())
        else:
            self.kind_label.configure(text="Search")
        if self._after_id is not None:
            self.after_cancel(self._after_id)
        self._after_id = self.after(180, self._kick)

    def _kick(self) -> None:
        if self._after_id is not None:
            self.after_cancel(self._after_id)
            self._after_id = None
        self._generation += 1
        generation = self._generation
        text = self.query_var.get()
        explain = bool(self.explain_var.get())
        threading.Thread(
            target=self._worker,
            args=(generation, text, explain),
            daemon=True,
        ).start()

    def _worker(self, generation: int, text: str, explain: bool) -> None:
        embedder = None
        embedder_error = None
        if text.strip() and classify(text) == "description":
            embedder, embedder_error = self._slot.resolve()
        try:
            view = execute_search(
                self.config_dir,
                text,
                limit=self.limit,
                explain=explain,
                embedder=embedder,
                embedder_error=embedder_error,
            )
        except Exception as exc:
            view = SearchView(
                query=text.strip(),
                kind="",
                kind_label="",
                lanes=[],
                hits=[],
                tree=[],
                sentence=None,
                error=str(exc),
                notice=None,
            )
        try:
            self.after(0, lambda: self._apply_if_current(generation, view))
        except (RuntimeError, tk.TclError):
            return

    def _apply_if_current(self, generation: int, view: SearchView) -> None:
        if generation != self._generation:
            return
        try:
            alive = bool(self.winfo_exists())
        except tk.TclError:
            return
        if not alive:
            return
        self.apply_view(view)

    def apply_view(self, view: SearchView) -> None:
        """Render a search result. Tests call this without waiting on the debounce."""
        self._view = view
        self._selected = 0
        self._paint_lanes(view)
        if view.kind_label:
            self.kind_label.configure(text=view.kind_label.upper())
        if view.sentence:
            self.sentence.configure(text=view.sentence)
            self.sentence.grid()
        else:
            self.sentence.grid_remove()
        self._clear_results()
        if view.error:
            self._show_prompt(view.error)
        elif not view.query:
            self._show_prompt("Type a filename, or a sentence about what the file contains.")
        elif not view.hits:
            self._show_prompt("No matches.")
        else:
            for index, hit in enumerate(view.hits):
                self._cards.append(self._card(index, hit))
        self._paint_selection()
        self._show_detail()
        self._fill_tree(view)
        self.status.configure(text=self._status_text(view))

    def _card(self, index: int, hit: HitView) -> tk.Frame:
        frame = tk.Frame(self.result_box, bg=_CARD, cursor="hand2")
        frame.pack(fill="x", padx=8, pady=2)
        top = tk.Frame(frame, bg=_CARD)
        top.pack(fill="x", padx=10, pady=(8, 0))
        title = tk.Label(top, text=hit.name, bg=_CARD, fg=_TEXT, font=(self._font, 12, "bold"), anchor="w")
        title.pack(side="left")
        lane_bg, lane_fg = _LANE_ON.get(hit.lane, (_LINE, _MUTED))
        lane = tk.Label(
            top,
            text=hit.lane,
            bg=lane_bg,
            fg=lane_fg,
            font=(self._font, 8, "bold"),
            padx=6,
            pady=1,
        )
        lane._ff_lane = True  # type: ignore[attr-defined]
        lane.pack(side="right")
        where = hit.relative if hit.relative != hit.name else hit.path
        if hit.line is not None:
            where = f"{where}:{hit.line}"
        meta = tk.Label(frame, text=where, bg=_CARD, fg=_MUTED, font=(self._font, 9), anchor="w")
        meta.pack(fill="x", padx=10, pady=(2, 0))
        snippet = tk.Label(
            frame,
            text=hit.snippet,
            bg=_CARD,
            fg=_MUTED,
            font=(self._font, 10),
            anchor="w",
            justify="left",
            wraplength=460,
        )
        snippet.pack(fill="x", padx=10, pady=(2, 8))
        self._snippets.append(snippet)
        for widget in (frame, top, title, lane, meta, snippet):
            widget.bind("<Button-1>", lambda _e, i=index: self._select(i))
            widget.bind("<Double-Button-1>", lambda _e, i=index: self._open_index(i))
            self._bind_wheel(widget)
        frame._ff_bits = (top, title, lane, meta, snippet)  # type: ignore[attr-defined]
        return frame

    def _select(self, index: int) -> None:
        if not self._view.hits:
            return
        self._selected = max(0, min(index, len(self._view.hits) - 1))
        self._paint_selection()
        self._show_detail()
        self._reveal_card()
        self._sync_tree()

    def _move(self, step: int):
        def handler(_event):
            if not self._view.hits:
                return "break"
            self._select(self._selected + step)
            return "break"

        return handler

    def _paint_selection(self) -> None:
        for index, frame in enumerate(self._cards):
            bg = _CARD_ON if index == self._selected else _CARD
            bits = getattr(frame, "_ff_bits", ())
            frame.configure(bg=bg)
            for widget in bits:
                if getattr(widget, "_ff_lane", False):
                    continue
                widget.configure(bg=bg)

    def _show_detail(self) -> None:
        for child in self.crumb_row.winfo_children():
            child.destroy()
        hits = self._view.hits
        if not hits:
            self.full_path.configure(text="")
            _set_text(self.match, "")
            return
        hit = hits[self._selected]
        for index, crumb in enumerate(hit.crumbs):
            if index:
                tk.Label(self.crumb_row, text="/", bg=_PANEL, fg=_FAINT, font=(self._font, 11)).pack(
                    side="left", padx=2
                )
            last = index == len(hit.crumbs) - 1
            tk.Label(
                self.crumb_row,
                text=crumb,
                bg=_CARD_ON if last and crumb != "…" else _PANEL,
                fg=_TEXT if last else _MUTED,
                font=(self._font, 10, "bold" if last else "normal"),
                padx=5,
                pady=2,
            ).pack(side="left")
        located = hit.path if hit.line is None else f"{hit.path}:{hit.line}"
        self.full_path.configure(text=located)
        _set_text(self.match, hit.detail or "No matching chunk.")

    def _fill_tree(self, view: SearchView) -> None:
        self._syncing = True
        self._path_iids = {}
        self._iid_paths = {}
        self._tree_seq = 0
        try:
            self.tree.delete(*self.tree.get_children())
            for node in view.tree:
                self._insert_node("", node)
        finally:
            self._syncing = False
        self._sync_tree()

    def _insert_node(self, parent: str, node) -> None:
        self._tree_seq += 1
        iid = f"n{self._tree_seq}"
        tag = "file" if node.path else "dir"
        self.tree.insert(parent, "end", iid=iid, text=node.name, open=True, tags=(tag,))
        if node.path:
            self._path_iids[node.path] = iid
            self._iid_paths[iid] = node.path
        for child in node.children:
            self._insert_node(iid, child)

    def _sync_tree(self) -> None:
        hits = self._view.hits
        if not hits:
            return
        iid = self._path_iids.get(hits[self._selected].path)
        if iid is None or not self.tree.exists(iid):
            return
        self._syncing = True
        try:
            self.tree.selection_set(iid)
            self.tree.see(iid)
        finally:
            self._syncing = False

    def _on_tree_select(self, _event) -> None:
        if self._syncing:
            return
        selected = self.tree.selection()
        if not selected:
            return
        path = self._iid_paths.get(selected[0])
        if path is None:
            return
        for index, hit in enumerate(self._view.hits):
            if hit.path == path:
                self._selected = index
                self._paint_selection()
                self._show_detail()
                self._reveal_card()
                return

    def _open_tree(self, _event) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        path = self._iid_paths.get(selected[0])
        if path is None:
            return
        for index, hit in enumerate(self._view.hits):
            if hit.path == path:
                self._open_index(index)
                return

    def _open_selected(self, _event=None):
        self._open_index(self._selected)
        return "break"

    def _open_index(self, index: int) -> None:
        if not self._view.hits:
            return
        hit = self._view.hits[index]
        argv = open_argv(hit.path, hit.line)
        try:
            if argv is None:
                if sys.platform == "win32":
                    os_startfile(hit.path)
                    return
                raise OSError("No file opener is available")
            subprocess.Popen(
                argv,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self.status.configure(text=f"Could not open {hit.name}: {exc}")
            return
        self.status.configure(text=f"Opened {hit.name}")

    def _copy_path(self, _event=None):
        try:
            if self.entry.selection_present():
                return None
        except tk.TclError:
            return None
        if not self._view.hits:
            return "break"
        path = self._view.hits[self._selected].path
        self.clipboard_clear()
        self.clipboard_append(path)
        self.status.configure(text="Copied path")
        return "break"

    def _paint_lanes(self, view: SearchView) -> None:
        for child in self.lane_row.winfo_children():
            child.destroy()
        lanes = view.lanes or SearchView.blank().lanes
        for lane in lanes:
            if lane.state == "on":
                bg, fg = _LANE_ON[lane.key]
                text = lane.label
            elif lane.state == "missing":
                bg, fg = _PANEL, _WARN
                text = f"{lane.label} off"
            else:
                bg, fg = _BG, _FAINT
                text = lane.label
            tk.Label(
                self.lane_row,
                text=text,
                bg=bg,
                fg=fg,
                font=(self._font, 9),
                padx=7,
                pady=2,
            ).pack(side="left", padx=(0, 4))

    def _clear_results(self) -> None:
        for child in self.result_box.winfo_children():
            child.destroy()
        self._cards = []
        self._snippets = []

    def _show_prompt(self, text: str) -> None:
        tk.Label(
            self.result_box,
            text=text,
            bg=_PANEL,
            fg=_MUTED,
            font=(self._font, 11),
            anchor="w",
            justify="left",
            wraplength=420,
        ).pack(fill="x", padx=16, pady=16)

    def _reveal_card(self) -> None:
        if not self._cards:
            return
        self.update_idletasks()
        card = self._cards[self._selected]
        total = max(1, self.result_box.winfo_height())
        self.canvas.yview_moveto(max(0, card.winfo_y() - 8) / total)

    def _bind_wheel(self, widget) -> None:
        widget.bind("<Button-4>", self._wheel, add="+")
        widget.bind("<Button-5>", self._wheel, add="+")
        widget.bind("<MouseWheel>", self._wheel, add="+")

    def _wheel(self, event):
        if getattr(event, "num", None) == 4:
            self.canvas.yview_scroll(-3, "units")
        elif getattr(event, "num", None) == 5:
            self.canvas.yview_scroll(3, "units")
        else:
            step = int(-event.delta / 120) if event.delta else -1
            self.canvas.yview_scroll(step or -1, "units")
        return "break"

    def _stretch_results(self, event) -> None:
        self.canvas.itemconfigure(self._window_id, width=event.width)
        wrap = max(160, event.width - 36)
        for label in self._snippets:
            label.configure(wraplength=wrap)

    def _status_text(self, view: SearchView) -> str:
        if view.error:
            return view.error
        if not view.query:
            return ""
        noun = "result" if len(view.hits) == 1 else "results"
        status = f"{len(view.hits)} {noun}"
        if view.notice:
            return f"{status} · {view.notice}"
        return status

    def _rewrap_path(self, event) -> None:
        self.full_path.configure(wraplength=max(120, event.width - 28))


def os_startfile(path: str) -> None:
    startfile = getattr(os, "startfile", None)
    if startfile is None:
        raise OSError("startfile is unavailable")
    startfile(path)


def _kind_label(kind: str) -> str:
    return {"name": "Name", "description": "Description", "exact": "Exact"}.get(kind, "Search")


def _set_text(widget, value: str) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", value)
    widget.configure(state="disabled")


def _pick_font() -> str:
    if tkfont is None:
        return "TkDefaultFont"
    try:
        families = set(tkfont.families())
    except tk.TclError:
        return "TkDefaultFont"
    for name in ("Ubuntu", "Cantarell", "DejaVu Sans", "Segoe UI", "Liberation Sans"):
        if name in families:
            return name
    return "TkDefaultFont"
