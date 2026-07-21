#!/usr/bin/env python3
"""
GUI App (Tkinter) for the API tool:
- Uses api_engine.py for networking, logging, session export, cURL & Postman parsing.
- Non-blocking requests via threading (keeps UI responsive).
- cURL paste-and-parse; request builder (method/URL/headers/payload); response viewer.
- Load Postman collections; export session; global SSL toggle.

Tabs:
- Body, Schema, Compare

Batch Run:
- Series/Parallel (Same Request) and Series (CSV), minimal templating.

NEW (Collection Variables - crash resilient temp file):
- Per-folder variables in memory with persistence to ./temp.collection.vars.json.
- Variables Dialog (Tools → Collection Variables…) to add/edit/delete and save.
- On load of a Postman collection, imports its top-level "variable" array into temp store.
- On send, api_engine applies {{var}} from temp store, so scratchpad also works.
- On export, api_engine injects variables and deletes temp var file. GUI reloads (becomes empty).
"""

import threading
import queue
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from typing import Dict, Any, Optional, List

# Import the engine (must be in the same folder)
import api_engine as eng

# NEW: temp var store
from temp_var_store import TempVarStore, TEMP_VARS_FILENAME

# --- NEW imports for batch run ---
import csv
import time
from concurrent.futures import ThreadPoolExecutor
import re
import shlex  # for cURL quoting in copy_as_curl
import urllib.parse

# ---------------------------- UI constants -----------------------------------
DEFAULT_FOLDER = Path(".")
MAX_UI_BODY_CHARS = 200_000  # truncate huge bodies in UI; logs keep full content


# --- BEGIN ADD: extractor index filename (module-level constant) ---
_EXTRACTORS_INDEX_FILENAME = "extractors.index.json"
# --- END ADD ---


class ApiGuiApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("API Tool")
        self.geometry("1200x860")

        # State
        import os
        self.folder = (Path(__file__).resolve().parent.parent / "artifacts")
        os.makedirs(self.folder, exist_ok=True) # Ensure folder exists
        self.logger = eng.configure_logger(self.folder / "logger.txt")
        eng._load_extractors(self.folder)  # NEW
        

        self.queue = queue.Queue()

        # Compare state (pair buffer)
        self.compare_var = tk.BooleanVar(value=False)
        self._compare_pending: Optional[Dict[str, Any]] = None  # {"url","status","json"}

        # Batch run state
        self._batch_running = False
        self._batch_cancelled = False
        self._batch_total = 0
        self._batch_completed = 0
        self._parallel_executor = None
        self._parallel_prev_compare_state = None

        # NEW: variables store (temp per-folder)
        self.vars = TempVarStore(self.folder / TEMP_VARS_FILENAME)
        from session_controller import SessionController; self.ctrl = SessionController()

        # Build UI     
        self._last_resp_headers: Dict[str, str] = {}
        self._last_resp_body_text: str = ""
        self._last_resp_elapsed_ms: Optional[float] = None
        self._last_resp_size_bytes: Optional[int] = None
        self._last_template_url: str = ""
        self._last_method: str = "GET"
        self._last_item_path: Optional[str] = None  # if loaded from collection

        # --- Theme / styling ---
        self.configure(background="#e8f0fe")  # light blue background
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background="#e8f0fe", foreground="#1a1a1a",
                        font=("Segoe UI", 9, "bold"))
        style.configure("TFrame", background="#e8f0fe")
        style.configure("TLabelframe", background="#e8f0fe")
        style.configure("TLabelframe.Label", background="#e8f0fe", foreground="#1a1a1a",
                        font=("Segoe UI", 9, "bold"))
        style.configure("TLabel", background="#e8f0fe", foreground="#1a1a1a")
        style.configure("TButton", font=("Segoe UI", 9, "bold"))
        style.configure("TNotebook", background="#e8f0fe")
        style.configure("TNotebook.Tab", font=("Segoe UI", 9, "bold"))
        style.configure("TPanedwindow", background="#e8f0fe")

        self._build_menu()
        self._build_layout()
        self._update_ssl_label()
        self._update_redirects_label()
        self.bind_all("<Control-f>", self._on_ctrl_f)

        # Apply text widget enhancements (undo/redo, smart double-click)
        from text_helpers import setup_text_widgets
        setup_text_widgets(self)

        # Attach autocomplete for {{variable}} placeholders
        from autocomplete import setup_autocomplete
        setup_autocomplete(self)

        # Attach Ctrl+Click JSON path picker on response body
        from json_path_picker import bind_json_path_picker
        bind_json_path_picker(self)

        # Intercept window close for auto-save prompt
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Start queue pump
        self.after(100, self._process_queue)

    # ---------------------------- UI Build -----------------------------------
    def _build_menu(self):
        menubar = tk.Menu(self)

        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Choose Working Folder...", command=self.choose_folder)
        filemenu.add_separator()
        filemenu.add_command(label="Export Session to Postman...", command=self.export_session)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=self.destroy)
        menubar.add_cascade(label="File", menu=filemenu)

        tools = tk.Menu(menubar, tearoff=0)
        tools.add_command(label="Collection Variables...", command=self.open_vars_dialog)  # NEW
        menubar.add_cascade(label="Tools", menu=tools)

        settings = tk.Menu(menubar, tearoff=0)
        settings.add_command(label="Toggle Disable SSL (global)", command=self.toggle_ssl)
        settings.add_command(label="Toggle Follow Redirects (global)", command=self.toggle_redirects)
        menubar.add_cascade(label="Settings", menu=settings)

        self.config(menu=menubar)

    def _build_layout(self):
        # Top status bar
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=8, pady=4)
        self.lbl_folder = ttk.Label(top, text=f"Folder: {self.folder}")
        self.lbl_folder.pack(side=tk.LEFT)

        self.lbl_progress = ttk.Label(top, text="")
        self.lbl_progress.pack(side=tk.RIGHT, padx=(8, 0))
        self.lbl_ssl = ttk.Label(top, text="")
        self.lbl_ssl.pack(side=tk.RIGHT)
        self.lbl_redirects = ttk.Label(top, text="")
        self.lbl_redirects.pack(side=tk.RIGHT, padx=(8, 0))

        main = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(main, width=340)
        main.add(left, weight=1)

        right = ttk.Frame(main)
        main.add(right, weight=4)

        frm_coll = ttk.LabelFrame(left, text="Collection Items")
        frm_coll.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        from tree_sidebar import TreeSidebar
        self._tree_sidebar = TreeSidebar(frm_coll, self)
        self.lst_items = self._tree_sidebar  # compatibility alias
        from collection_editor import CollectionEditor; CollectionEditor.inject_controls(self, frm_coll)

        right_split = ttk.Panedwindow(right, orient=tk.VERTICAL)
        right_split.pack(fill=tk.BOTH, expand=True)
        self._right_split = right_split
        self._default_split_applied = False

        request_host = ttk.Frame(right_split)
        response_host = ttk.Frame(right_split)
        right_split.add(request_host, weight=1)
        right_split.add(response_host, weight=4)
        self.after(0, self._apply_default_split_sizes)

        frm_req = ttk.LabelFrame(request_host, text="Request")
        frm_req.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        ttk.Label(frm_req, text="Method").grid(row=0, column=0, sticky="w")

        row0_inner = ttk.Frame(frm_req)
        row0_inner.grid(row=0, column=1, columnspan=3, sticky="we", padx=4, pady=2)

        self.method_var = tk.StringVar(value="GET")
        self.cmb_method = ttk.Combobox(
            row0_inner, textvariable=self.method_var,
            values=["GET", "POST", "PUT", "PATCH", "DELETE"], width=8
        )
        self.cmb_method.pack(side=tk.LEFT)

        ttk.Label(row0_inner, text="  Name:").pack(side=tk.LEFT)
        self.ent_name = ttk.Entry(row0_inner)
        self.ent_name.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        from sidebar_manager import SidebarManager
        ttk.Button(
            row0_inner,
            text="Rename",
            width=7,
            command=lambda: SidebarManager.refresh_sidebar_label(self)
        ).pack(side=tk.LEFT, padx=2)

        ttk.Label(frm_req, text="URL").grid(row=1, column=0, sticky="w")
        row1_inner = ttk.Frame(frm_req)
        row1_inner.grid(row=1, column=1, columnspan=3, sticky="we", padx=4, pady=2)
        row1_inner.columnconfigure(0, weight=1)

        self.ent_url = ttk.Entry(row1_inner)
        self.ent_url.grid(row=0, column=0, sticky="we")
        self.ent_url.bind("<Return>", lambda e: self.send_request())
        ttk.Button(row1_inner, text="Send", command=self.send_request).grid(row=0, column=1, sticky="e", padx=(8, 0))
        frm_req.columnconfigure(1, weight=1)
        frm_req.columnconfigure(3, weight=1)

        row_btns = ttk.Frame(frm_req)
        row_btns.grid(row=2, column=0, columnspan=4, sticky="we", padx=4, pady=(0, 4))

        # Row 1: cURL, Load, Run..., Cancel, Validate, Compare
        row1 = ttk.Frame(row_btns)
        row1.pack(fill=tk.X, pady=(0, 2))
        ttk.Button(row1, text="Copy as cURL", command=self.copy_as_curl).pack(side=tk.LEFT)
        ttk.Button(row1, text="Paste cURL...", command=self.open_curl_popup).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(row1, text="Load Postman Collection...", command=self.load_collection).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(row1, text="Run...", command=self.open_run_dialog).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(row1, text="Cancel Run", command=lambda: setattr(self, "_batch_cancelled", True)).pack(side=tk.LEFT, padx=(8, 0))
        self.validate_schema_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row1, text="Validate schema", variable=self.validate_schema_var).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Checkbutton(
            row1, text="Compare", variable=self.compare_var, command=self._on_compare_toggled
        ).pack(side=tk.LEFT, padx=(8, 0))

        # Row 2: Collection Variables, Run Collection, Run Selected, Run N Times
        row2 = ttk.Frame(row_btns)
        row2.pack(fill=tk.X)
        ttk.Button(row2, text="Set Collection Variables", command=self.open_set_collect_vars_dialog).pack(side=tk.LEFT)
        ttk.Button(row2, text="Run Collection (All)", command=self.open_run_collection_delay_dialog).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(row2, text="Run Selected...", command=self.open_selective_run_dialog).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(row2, text="Run N Times...", command=self.open_run_collection_n_dialog).pack(side=tk.LEFT, padx=(8, 0))

        req_tabs = ttk.Notebook(frm_req)
        req_tabs.grid(row=3, column=0, columnspan=4, sticky="nsew", padx=4, pady=4)
        self.req_tabs = req_tabs
        frm_req.rowconfigure(3, weight=1)
        req_tabs.bind("<<NotebookTabChanged>>", self._on_req_tab_changed)

        tab_params = ttk.Frame(req_tabs)
        req_tabs.add(tab_params, text="Params")
        self._req_tab_params = tab_params

        self.tree_params = ttk.Treeview(tab_params, columns=("key", "value"), show="headings", selectmode="browse", height=6)
        self.tree_params.heading("key", text="Key")
        self.tree_params.heading("value", text="Value")
        self.tree_params.column("key", width=220, anchor="w")
        self.tree_params.column("value", width=420, anchor="w")
        self.tree_params.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 2))

        row_params = ttk.Frame(tab_params)
        row_params.pack(fill=tk.X, padx=4, pady=(0, 4))
        ttk.Label(row_params, text="Key").grid(row=0, column=0, sticky="w")
        self.ent_param_key = ttk.Entry(row_params, width=20)
        self.ent_param_key.grid(row=0, column=1, sticky="we", padx=(6, 10))
        ttk.Label(row_params, text="Value").grid(row=0, column=2, sticky="w")
        self.ent_param_value = ttk.Entry(row_params, width=30)
        self.ent_param_value.grid(row=0, column=3, sticky="we", padx=(6, 10))
        row_params.columnconfigure(1, weight=1)
        row_params.columnconfigure(3, weight=2)
        ttk.Button(row_params, text="Add", command=self._params_add).grid(row=0, column=4, sticky="e")
        ttk.Button(row_params, text="Delete", command=self._params_delete).grid(row=0, column=5, sticky="e", padx=(8, 0))
        ttk.Button(row_params, text="Load from URL", command=self._params_load_from_url).grid(row=0, column=6, sticky="e", padx=(8, 0))
        ttk.Button(row_params, text="Apply to URL", command=self._params_apply_to_url).grid(row=0, column=7, sticky="e", padx=(8, 0))

        tab_headers = ttk.Frame(req_tabs)
        req_tabs.add(tab_headers, text="Headers")
        ttk.Label(tab_headers, text="Headers (JSON or 'Key: Value' per line)").pack(anchor="w", padx=4, pady=(4, 0))
        self.txt_headers = tk.Text(tab_headers, height=8)
        self.txt_headers.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        # Alternating line colors for readability (against light blue app background)
        self.txt_headers.tag_configure("even_line", background="#c8e6c9")
        self.txt_headers.tag_configure("odd_line", background="#f5f9ff")
        self.txt_headers.bind("<KeyRelease>", lambda e: self._colorize_headers())
        self.txt_headers.bind("<<Modified>>", lambda e: self._colorize_headers())

        tab_body = ttk.Frame(req_tabs)
        req_tabs.add(tab_body, text="Body")
        btns = ttk.Frame(tab_body)
        btns.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=(0, 4))
        ttk.Button(btns, text="Validate JSON", command=self.validate_json).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Pretty JSON", command=self.pretty_json).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Clear Body", command=lambda: self.txt_payload.delete("1.0", tk.END)).pack(side=tk.LEFT, padx=2)

        self.txt_payload = tk.Text(tab_body)
        payload_scroll = ttk.Scrollbar(tab_body, orient=tk.VERTICAL, command=self.txt_payload.yview)
        self.txt_payload.configure(yscrollcommand=payload_scroll.set)
        payload_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_payload.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 2))

        # --- Pre-request Script tab ---
        tab_prerequest = ttk.Frame(req_tabs)
        req_tabs.add(tab_prerequest, text="Pre-request Script")
        ttk.Label(tab_prerequest, text="Runs before the request is sent (Python with pm.* API)").pack(anchor="w", padx=4, pady=(4, 0))
        self.txt_prerequest = tk.Text(tab_prerequest, height=8)
        self.txt_prerequest.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # --- Tests (Post-response Script) tab ---
        tab_tests = ttk.Frame(req_tabs)
        req_tabs.add(tab_tests, text="Tests")
        ttk.Label(tab_tests, text="Runs after the response is received (Python with pm.* API)").pack(anchor="w", padx=4, pady=(4, 0))
        self.txt_tests = tk.Text(tab_tests, height=8)
        self.txt_tests.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        frm_resp = ttk.LabelFrame(response_host, text="Response")
        frm_resp.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        resp_top = ttk.Frame(frm_resp)
        resp_top.pack(fill=tk.X, padx=4, pady=2)
        self.lbl_status = ttk.Label(resp_top, text="Status: -")
        self.lbl_status.pack(side=tk.LEFT)
        self.lbl_metrics = ttk.Label(resp_top, text="")
        self.lbl_metrics.pack(side=tk.LEFT, padx=(10, 0))

        self.nb_resp = ttk.Notebook(frm_resp)
        self.nb_resp.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        tab_body = ttk.Frame(self.nb_resp)
        self.nb_resp.add(tab_body, text="Body")
        self._resp_tab_body = tab_body
        self.txt_resp_body = tk.Text(tab_body)
        resp_body_scroll = ttk.Scrollbar(tab_body, orient=tk.VERTICAL, command=self.txt_resp_body.yview)
        self.txt_resp_body.configure(yscrollcommand=resp_body_scroll.set)
        resp_body_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.txt_resp_body.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        tab_resp_headers = ttk.Frame(self.nb_resp)
        self.nb_resp.add(tab_resp_headers, text="Headers")
        self._resp_tab_headers = tab_resp_headers
        self.txt_resp_headers = tk.Text(tab_resp_headers)
        self.txt_resp_headers.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        tab_schema = ttk.Frame(self.nb_resp)
        self.nb_resp.add(tab_schema, text="Schema")
        self._resp_tab_schema = tab_schema
        self.lbl_schema_result = ttk.Label(tab_schema, text="Schema: (validation not run)")
        self.lbl_schema_result.pack(anchor="w", padx=2, pady=(4, 2))
        self.txt_schema_details = tk.Text(tab_schema)
        self.txt_schema_details.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 4))
        self.txt_schema_details.config(state=tk.DISABLED)

        tab_compare = ttk.Frame(self.nb_resp)
        self.nb_resp.add(tab_compare, text="Compare")
        self._resp_tab_compare = tab_compare
        self.lbl_compare_result = ttk.Label(tab_compare, text="Compare: (not running)")
        self.lbl_compare_result.pack(anchor="w", padx=2, pady=(4, 2))
        self.txt_compare_details = tk.Text(tab_compare)
        self.txt_compare_details.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 4))
        self.txt_compare_details.config(state=tk.DISABLED)

        try:
            self.nb_resp.select(0)
        except Exception:
            pass

        ttk.Button(frm_resp, text="Export Session to Postman...", command=self.export_session).pack(anchor="e", padx=4, pady=4)


    # ---------------------------- Helpers ------------------------------------
    def _update_ssl_label(self):
        self.lbl_ssl.config(text=f"SSL verification: {'DISABLED' if eng.DISABLE_SSL else 'ENABLED'}")

    def _update_redirects_label(self):
        self.lbl_redirects.config(text=f"Redirects: {'ON' if eng.FOLLOW_REDIRECTS else 'OFF'}")

    def _flash_response(self):
        """Brief visual flash on response area to indicate a new response arrived."""
        flash_color = "#a5d6a7"  # medium green, visible against light blue
        try:
            original_bg = self.txt_resp_body.cget("background") or "#f5f9ff"
        except Exception:
            original_bg = "#f5f9ff"
        self.txt_resp_body.config(background=flash_color)
        self.after(300, lambda: self.txt_resp_body.config(background=original_bg))

    def _colorize_headers(self):
        """Applies alternating background colors to each line in the headers widget."""
        txt = self.txt_headers
        txt.tag_remove("even_line", "1.0", tk.END)
        txt.tag_remove("odd_line", "1.0", tk.END)
        line_count = int(txt.index("end-1c").split(".")[0])
        for i in range(1, line_count + 1):
            tag = "even_line" if i % 2 == 0 else "odd_line"
            txt.tag_add(tag, f"{i}.0", f"{i}.end")
        # Reset modified flag to allow future events
        try:
            txt.edit_modified(False)
        except Exception:
            pass

    def _colorize_json(self, txt_widget: tk.Text):
        """Colorize JSON keys and values in a Text widget. Keys = blue, values = green."""
        txt_widget.tag_remove("json_key", "1.0", tk.END)
        txt_widget.tag_remove("json_value", "1.0", tk.END)
        txt_widget.tag_config("json_key", foreground="#0451a5")
        txt_widget.tag_config("json_value", foreground="#098658")

        # Pattern: lines in pretty-printed JSON look like:  "key": value
        # We match the key (quoted string before colon) and the value portion after colon
        content = txt_widget.get("1.0", "end-1c")
        for i, line in enumerate(content.split("\n"), start=1):
            # Match "key": ...
            m = re.match(r'^(\s*)"(.+?)"\s*:', line)
            if m:
                indent_len = len(m.group(1))
                key_start = indent_len  # the opening quote
                key_end = indent_len + len(m.group(2)) + 2  # includes both quotes
                txt_widget.tag_add("json_key", f"{i}.{key_start}", f"{i}.{key_end}")

                # Value starts after the colon+space
                colon_pos = line.index(":", key_end)
                val_start = colon_pos + 1
                # Skip whitespace after colon
                while val_start < len(line) and line[val_start] == " ":
                    val_start += 1
                val_text = line[val_start:].rstrip(",")
                if val_text and val_text not in ("{", "[", "{}", "[]"):
                    txt_widget.tag_add("json_value", f"{i}.{val_start}", f"{i}.{len(line.rstrip(','))}")
            else:
                # Standalone array values (e.g. items in a list)
                stripped = line.strip().rstrip(",")
                if stripped and stripped not in ("{", "}", "[", "]", "},", "],"):
                    indent_len = len(line) - len(line.lstrip())
                    txt_widget.tag_add("json_value", f"{i}.{indent_len}", f"{i}.{indent_len + len(stripped)}")

    def choose_folder(self):
        sel = filedialog.askdirectory(initialdir=str(self.folder))
        if not sel:
            return
        self.folder = Path(sel).resolve()
        self.lbl_folder.config(text=f"Folder: {self.folder}")
        # Rebind logger
        self.logger = eng.configure_logger(self.folder / "logger.txt")
        # Reload variables store (NEW)
        self.vars = TempVarStore(self.folder / TEMP_VARS_FILENAME)
        eng._load_extractors(self.folder)  # NEW
        messagebox.showinfo("Working Folder", f"Now using: {self.folder}")

    def _parse_headers_from_text(self, raw: str) -> Dict[str, str]:
        if not raw:
            return {}
        # Try JSON first
        if raw.startswith("{") and raw.endswith("}"):
            try:
                obj = json.loads(raw)
                return {str(k): str(v) for k, v in obj.items()}
            except json.JSONDecodeError:
                return {}
        headers: Dict[str, str] = {}
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
            else:
                parts = line.split(None, 1)
                if len(parts) == 2:
                    headers[parts[0]] = parts[1]
        return headers

    def _apply_default_split_sizes(self):
        paned = getattr(self, "_right_split", None)
        if paned is None:
            return
        if getattr(self, "_default_split_applied", False):
            return
        try:
            try:
                paned.paneconfigure(paned.panes()[0], minsize=240)
                paned.paneconfigure(paned.panes()[1], minsize=340)
            except Exception:
                pass
            h = paned.winfo_height()
            if h and h > 80:
                min_req = 240
                min_resp = 340
                max_req = max(min_req, h - min_resp)
                target = int(h * 0.5)
                target = max(min_req, min(max_req, target))
                paned.sashpos(0, target)
                self._default_split_applied = True
                return
        except Exception:
            return
        self.after(60, self._apply_default_split_sizes)

    def _format_bytes(self, n: Optional[int]) -> str:
        if n is None:
            return ""
        try:
            n = int(n)
        except Exception:
            return str(n)
        units = ["B", "KB", "MB", "GB"]
        size = float(n)
        for u in units:
            if size < 1024.0 or u == units[-1]:
                if u == "B":
                    return f"{int(size)} {u}"
                return f"{size:.1f} {u}"
            size /= 1024.0
        return f"{n} B"

    def _set_status_badge(self, status: Any):
        try:
            s = int(status)
        except Exception:
            try:
                self.lbl_status.config(style="TLabel")
            except Exception:
                pass
            return
        style = ttk.Style(self)
        if s >= 500:
            st = "Status.Error.TLabel"
            style.configure(st, foreground="#b00020")
        elif s >= 400:
            st = "Status.Warn.TLabel"
            style.configure(st, foreground="#c75b12")
        elif s >= 300:
            st = "Status.Info.TLabel"
            style.configure(st, foreground="#1565c0")
        elif s >= 200:
            st = "Status.Ok.TLabel"
            style.configure(st, foreground="#2e7d32")
        else:
            st = "TLabel"
        try:
            self.lbl_status.config(style=st)
        except Exception:
            pass

    def _on_ctrl_f(self, _evt=None):
        # Capture which text widget had focus BEFORE the search dialog steals it
        target = None
        try:
            focused = self.focus_get()
            if focused is self.txt_payload:
                target = self.txt_payload
        except Exception:
            pass
        self.open_response_search(target_widget=target)

    def _get_active_response_text_widget(self) -> Optional[tk.Text]:
        # Auto-detect: if the request payload has focus, search there instead
        try:
            focused = self.focus_get()
            if focused is self.txt_payload:
                return self.txt_payload
        except Exception:
            pass
        try:
            tab = self.nb_resp.select()
        except Exception:
            return None
        if tab == getattr(self, "_resp_tab_body", None):
            return self.txt_resp_body
        if tab == getattr(self, "_resp_tab_headers", None):
            return self.txt_resp_headers
        if tab == getattr(self, "_resp_tab_schema", None):
            return self.txt_schema_details
        if tab == getattr(self, "_resp_tab_compare", None):
            return self.txt_compare_details
        return self.txt_resp_body

    def open_response_search(self, target_widget=None):
        from search_manager import open_response_search
        open_response_search(self, target_widget)

    def _split_url_simple(self, url: str):
        base = url or ""
        frag = ""
        if "#" in base:
            base, frag = base.split("#", 1)
        query = ""
        if "?" in base:
            base, query = base.split("?", 1)
        return base, query, frag

    def _params_clear(self):
        try:
            for iid in self.tree_params.get_children():
                self.tree_params.delete(iid)
        except Exception:
            pass

    def _params_add(self):
        key = self.ent_param_key.get().strip()
        val = self.ent_param_value.get()
        if not key:
            return
        try:
            self.tree_params.insert("", tk.END, values=(key, val))
        except Exception:
            pass
        try:
            self.ent_param_key.delete(0, tk.END)
            self.ent_param_value.delete(0, tk.END)
        except Exception:
            pass

    def _params_delete(self):
        try:
            sel = self.tree_params.selection()
            for iid in sel:
                self.tree_params.delete(iid)
        except Exception:
            pass

    def _params_load_from_url(self):
        url = self.ent_url.get().strip()
        base, query, frag = self._split_url_simple(url)
        self._params_clear()
        if query:
            try:
                for k, v in urllib.parse.parse_qsl(query, keep_blank_values=True):
                    self.tree_params.insert("", tk.END, values=(k, v))
            except Exception:
                pass
        try:
            self.ent_param_key.delete(0, tk.END)
            self.ent_param_value.delete(0, tk.END)
        except Exception:
            pass

    def _params_apply_to_url(self):
        url = self.ent_url.get().strip()
        base, _query, frag = self._split_url_simple(url)
        pairs = []
        try:
            for iid in self.tree_params.get_children():
                k, v = self.tree_params.item(iid, "values")
                k = str(k).strip()
                if not k:
                    continue
                pairs.append((k, "" if v is None else str(v)))
        except Exception:
            pairs = []
        query = ""
        try:
            if pairs:
                query = urllib.parse.urlencode(pairs, doseq=True, quote_via=urllib.parse.quote)
        except Exception:
            query = ""
        out = base
        if query:
            out += "?" + query
        if frag:
            out += "#" + frag
        try:
            self.ent_url.delete(0, tk.END)
            self.ent_url.insert(0, out)
        except Exception:
            pass

    def _on_req_tab_changed(self, _evt=None):
        try:
            if self.req_tabs.select() == getattr(self, "_req_tab_params", None):
                self._params_load_from_url()
        except Exception:
            pass

    def _clear_response_view(self):
        try:
            self.lbl_status.config(text="Status: -")
        except Exception:
            pass
        try:
            self.lbl_metrics.config(text="")
        except Exception:
            pass
        try:
            self.txt_resp_headers.delete("1.0", tk.END)
            self.txt_resp_headers.insert(tk.END, "(none)")
        except Exception:
            pass
        try:
            self.txt_resp_body.delete("1.0", tk.END)
            self.txt_resp_body.insert(tk.END, "(empty)")
        except Exception:
            pass
        try:
            self.lbl_schema_result.config(text="Schema: (validation not run)")
            self.txt_schema_details.config(state=tk.NORMAL)
            self.txt_schema_details.delete("1.0", tk.END)
            self.txt_schema_details.config(state=tk.DISABLED)
        except Exception:
            pass
        try:
            self.lbl_compare_result.config(text="Compare: (not running)")
            self.txt_compare_details.config(state=tk.NORMAL)
            self.txt_compare_details.delete("1.0", tk.END)
            self.txt_compare_details.config(state=tk.DISABLED)
        except Exception:
            pass
        try:
            self.nb_resp.select(0)
        except Exception:
            pass

    def _load_response_snapshot(self, snap: Dict[str, Any]):
        if not isinstance(snap, dict):
            self._clear_response_view()
            return
        status = snap.get("status", "-")
        reason = snap.get("reason", "")
        headers = snap.get("headers") or {}
        body_text = snap.get("body_text") or ""
        elapsed_ms = snap.get("elapsed_ms")
        size_bytes = snap.get("size_bytes")

        try:
            self.lbl_status.config(text=f"Status: {status} {reason}".strip())
        except Exception:
            pass
        self._set_status_badge(status)
        if elapsed_ms is not None or size_bytes is not None:
            ms = ""
            try:
                ms = f"{float(elapsed_ms):.0f} ms" if elapsed_ms is not None else ""
            except Exception:
                ms = str(elapsed_ms)
            sz = self._format_bytes(size_bytes) if size_bytes is not None else ""
            txt = " | ".join([p for p in [ms, sz] if p])
            try:
                self.lbl_metrics.config(text=txt)
            except Exception:
                pass
        try:
            self.txt_resp_headers.delete("1.0", tk.END)
            self.txt_resp_headers.insert(tk.END, json.dumps(headers, indent=2) if headers else "(none)")
        except Exception:
            pass
        try:
            self.txt_resp_body.delete("1.0", tk.END)
            self.txt_resp_body.insert(tk.END, body_text if body_text else "(empty)")
            self._colorize_json(self.txt_resp_body)
        except Exception:
            pass
        self._last_resp_headers = dict(headers or {})
        self._last_resp_body_text = body_text if isinstance(body_text, str) else ""
        self._last_resp_elapsed_ms = elapsed_ms if isinstance(elapsed_ms, (int, float)) else None
        self._last_resp_size_bytes = size_bytes if isinstance(size_bytes, int) else None
        try:
            self.nb_resp.select(0)
        except Exception:
            pass


    def _show_request_response(self, method: str, url: str, headers: Dict[str, str], req_body: bytes,
                                   status: int, reason: str, resp_headers: Dict[str, str], resp_body,
                                   elapsed_ms: Optional[float] = None, size_bytes: Optional[int] = None):
        # Update UI panels (RESOLVED URL shown)
        self.lbl_status.config(text=f"Status: {status} {reason}")
        self._set_status_badge(status)
        if elapsed_ms is not None or size_bytes is not None:
            ms = ""
            try:
                ms = f"{float(elapsed_ms):.0f} ms" if elapsed_ms is not None else ""
            except Exception:
                ms = str(elapsed_ms)
            sz = self._format_bytes(size_bytes) if size_bytes is not None else ""
            self.lbl_metrics.config(text=" | ".join([p for p in [ms, sz] if p]))
        else:
            try:
                self.lbl_metrics.config(text="")
            except Exception:
                pass
        self.txt_resp_headers.delete("1.0", tk.END)
        self.txt_resp_headers.insert(tk.END, json.dumps(resp_headers, indent=2) if resp_headers else "(none)")

        self.txt_resp_body.delete("1.0", tk.END)
        
        # --- FIX: Handle both bytes and already-formatted strings ---
        if isinstance(resp_body, str):
            preview = resp_body if resp_body else "(empty)"
        else:
            preview = resp_body.decode("utf-8", errors="replace") if resp_body else "(empty)"
        # -------------------------------------------------------------

        if len(preview) > MAX_UI_BODY_CHARS:
            self.txt_resp_body.insert(tk.END, preview[:MAX_UI_BODY_CHARS] + "\n\n[Truncated in UI; full content in logger.txt]")
        else:
            self.txt_resp_body.insert(tk.END, preview)
        self._colorize_json(self.txt_resp_body)
        try:
            self.nb_resp.select(0)
        except Exception:
            pass

        # Log blocks (RESOLVED URL)
        req_lines = [
            f"REQUEST: {method} {url}",
            "Request Headers:",
            *(f" {k}: {v}" for k, v in headers.items()),
            "Request Body:",
            req_body.decode("utf-8", errors="replace") if req_body else "(empty)"
        ]
        eng.log_block(self.logger, "HTTP REQUEST", req_lines)

        resp_lines = [
            f"STATUS: {status} {reason}",
            "Response Headers:",
            *(f" {k}: {v}" for k, v in resp_headers.items()),
            "Response Body:",
            preview
        ]
        eng.log_block(self.logger, "HTTP RESPONSE", resp_lines)

        # --- BEGIN MOD: Pass raw bytes to schema/compare functions ---
        # Schema validation (if enabled)
        self._run_schema_validation_if_enabled(url, status, resp_headers, self._last_resp_body_bytes)

        # Pairwise compare (if enabled)
        self._run_compare_if_enabled(url, status, resp_headers, self._last_resp_body_bytes)
        # --- END MOD ---


    # ---------------------------- Schema tab ---------------------------------
    def _run_schema_validation_if_enabled(self, url: str, status: int, resp_headers: Dict[str, str], resp_body: bytes):
        self.lbl_schema_result.config(text="Schema: (validation not run)")
        self.txt_schema_details.config(state=tk.NORMAL)
        self.txt_schema_details.delete("1.0", tk.END)
        self.txt_schema_details.config(state=tk.DISABLED)

        if not self.validate_schema_var.get():
            return

        result = eng.validate_and_log_schema(
            url=url, status=status, headers=resp_headers, resp_body=resp_body,
            work_folder=self.folder, logger=self.logger
        )

        def _apply_ui():
            if not result["ran"]:
                reason = result.get("reason") or "skipped"
                self.lbl_schema_result.config(text=f"Schema: (skipped) — {reason}")
                return
            schema_name = result['schema_path'].name if result['schema_path'] else '(unknown)'
            if result["valid"]:
                self.lbl_schema_result.config(text=f"Schema: ✅ VALID — {schema_name}")
            else:
                self.lbl_schema_result.config(text=f"Schema: ❌ {result['count']} issue(s) — {schema_name}")
                self.txt_schema_details.config(state=tk.NORMAL)
                self.txt_schema_details.delete("1.0", tk.END)
                self.txt_schema_details.insert(tk.END, "\n".join(result["errors"]))
                self.txt_schema_details.config(state=tk.DISABLED)
                try:
                    self.nb_resp.select(getattr(self, "_resp_tab_schema", 0))
                except Exception:
                    pass

        self.after(0, _apply_ui)
        
    # ---------------------------- Compare tab --------------------------------
    def _on_compare_toggled(self):
        self._compare_pending = None
        self.lbl_compare_result.config(text="Compare: (not running)" if not self.compare_var.get() else "Compare: Waiting for first response...")
        self.txt_compare_details.config(state=tk.NORMAL)
        self.txt_compare_details.delete("1.0", tk.END)
        self.txt_compare_details.config(state=tk.DISABLED)

    def _run_compare_if_enabled(self, url: str, status: int, resp_headers: Dict[str, str], resp_body: bytes):
        self.txt_compare_details.config(state=tk.NORMAL)
        self.txt_compare_details.delete("1.0", tk.END)
        self.txt_compare_details.config(state=tk.DISABLED)

        if not self.compare_var.get():
            self.lbl_compare_result.config(text="Compare: (off)")
            self._compare_pending = None
            return

        if not eng._is_json_content_type(resp_headers):
            self.lbl_compare_result.config(text="Compare: (skipped — non-JSON Content-Type)")
            return
        ok, payload, perr = eng._safe_json_loads(resp_body)
        if not ok:
            self.lbl_compare_result.config(text=f"Compare: (skipped — invalid JSON: {perr})")
            return

        if self._compare_pending is None:
            self._compare_pending = {"url": url, "status": status, "json": payload}
            self.lbl_compare_result.config(text="Compare: First response stored. Send another to compare.")
            return

        diff = eng.run_diff(self._compare_pending["json"], payload)
        meta = {
            "url_a": self._compare_pending["url"], "status_a": self._compare_pending["status"],
            "url_b": url, "status_b": status
        }
        eng.log_diff_block(self.logger, meta, diff)
        if diff.get("valid"):
            self.lbl_compare_result.config(text="Compare: ✅ No differences")
            self.txt_compare_details.config(state=tk.NORMAL)
            self.txt_compare_details.insert(tk.END, "(No differences)")
            self.txt_compare_details.config(state=tk.DISABLED)
        else:
            self.lbl_compare_result.config(text=f"Compare: ❌ {diff.get('count', 0)} difference(s)")
            self.txt_compare_details.config(state=tk.NORMAL)
            self.txt_compare_details.insert(tk.END, "\n".join(diff.get("lines", [])))
            self.txt_compare_details.config(state=tk.DISABLED)
            try:
                self.nb_resp.select(getattr(self, "_resp_tab_compare", 0))
            except Exception:
                pass
        self._compare_pending = None

    # ---------------------------- Actions ------------------------------------
    def validate_json(self):
        raw = self.txt_payload.get("1.0", tk.END).strip()
        if not raw:
            messagebox.showinfo("Validate JSON", "Payload is empty.")
            return
        try:
            json.loads(raw)
            messagebox.showinfo("Validate JSON", "Valid JSON ✅")
        except json.JSONDecodeError as e:
            messagebox.showerror("Validate JSON", f"Invalid JSON:\n{e}")

    def pretty_json(self):
        raw = self.txt_payload.get("1.0", tk.END).strip()
        if not raw:
            return
        # Clear any previous error highlight
        self.txt_payload.tag_remove("json_error_line", "1.0", tk.END)
        try:
            obj = json.loads(raw)
            self.txt_payload.delete("1.0", tk.END)
            self.txt_payload.insert(tk.END, json.dumps(obj, indent=2))
            self._colorize_json(self.txt_payload)
        except json.JSONDecodeError as e:
            # Still format it best-effort so the user can see structure and fix it
            from text_helpers import best_effort_pretty_print, find_error_line_in_pretty, highlight_error_line
            formatted = best_effort_pretty_print(raw)
            self.txt_payload.delete("1.0", tk.END)
            self.txt_payload.insert(tk.END, formatted)
            self._colorize_json(self.txt_payload)
            # Highlight the error line in red
            err_line = find_error_line_in_pretty(formatted, e)
            highlight_error_line(self.txt_payload, err_line)
            messagebox.showwarning("Pretty JSON", f"JSON has a syntax error:\n{e.msg} (around line {e.lineno})\n\nFormatted best-effort. Error line highlighted in red.")

    def open_curl_popup(self):
        from curl_handler import open_curl_popup
        open_curl_popup(self)

    def parse_curl(self):
        from curl_handler import parse_curl
        parse_curl(self)

    def _close_curl_popup(self):
        from curl_handler import _close_curl_popup
        _close_curl_popup(self)

    def clear_collection(self):
        """Resets the collection state, sidebar, and UI fields to a blank slate."""
        # Clear session controller
        self.ctrl.requests.clear()
        self.ctrl.last_index = None

        # Clear sidebar listbox
        self.lst_items.delete(0, tk.END)

        # Clear UI fields
        self.ent_name.delete(0, tk.END)
        self.method_var.set("GET")
        self.ent_url.delete(0, tk.END)
        self.txt_headers.delete("1.0", tk.END)
        self.txt_payload.delete("1.0", tk.END)
        self.txt_prerequest.delete("1.0", tk.END)
        self.txt_tests.delete("1.0", tk.END)

        # Clear response view
        self._clear_response_view()

    def new_request(self):
        """Deselects current item and clears UI for a fresh request."""
        # Save current request state before switching away
        if self.ctrl.last_index is not None and self.ctrl.last_index < len(self.ctrl.requests):
            self.ctrl.requests[self.ctrl.last_index].update({
                "name": self.ent_name.get().strip(),
                "method": self.method_var.get(),
                "url": self.ent_url.get(),
                "headers": self._parse_headers_from_text(self.txt_headers.get("1.0", "end-1c")),
                "body_bytes": self.txt_payload.get("1.0", "end-1c").encode("utf-8"),
                "prerequest_script": self.txt_prerequest.get("1.0", "end-1c"),
                "test_script": self.txt_tests.get("1.0", "end-1c"),
            })

        # Deselect and reset tracking
        self.lst_items.selection_clear(0, tk.END)
        self.ctrl.last_index = None

        # Clear UI fields
        self.ent_name.delete(0, tk.END)
        self.method_var.set("GET")
        self.ent_url.delete(0, tk.END)
        self.txt_headers.delete("1.0", tk.END)
        self.txt_payload.delete("1.0", tk.END)
        self.txt_prerequest.delete("1.0", tk.END)
        self.txt_tests.delete("1.0", tk.END)
        self._clear_response_view()

    def _on_close(self):
        """Intercepts window close — prompts to save collection before exiting."""
        # If nothing loaded, just close
        if not self.ctrl.requests:
            self.destroy()
            return

        # Save current UI state to the active request before exporting
        if self.ctrl.last_index is not None and self.ctrl.last_index < len(self.ctrl.requests):
            self.ctrl.requests[self.ctrl.last_index].update({
                "name": self.ent_name.get().strip(),
                "method": self.method_var.get(),
                "url": self.ent_url.get(),
                "headers": self._parse_headers_from_text(self.txt_headers.get("1.0", "end-1c")),
                "body_bytes": self.txt_payload.get("1.0", "end-1c").encode("utf-8"),
                "prerequest_script": self.txt_prerequest.get("1.0", "end-1c"),
                "test_script": self.txt_tests.get("1.0", "end-1c"),
            })

        answer = messagebox.askyesnocancel(
            "Save Collection",
            "Do you want to save the current collection before closing?"
        )
        if answer is None:
            # Cancel — don't close
            return
        if answer:
            # Yes — export with timestamp
            try:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                collection_name = f"AutoSave_{timestamp}"

                # Write session.jsonl
                session_file = Path(self.folder) / "session.jsonl"
                with open(session_file, "w", encoding="utf-8") as f:
                    for req in self.ctrl.get_all():
                        export_data = req.copy()
                        if not export_data.get("name"):
                            export_data["name"] = f"{req.get('method', 'GET')} {req.get('url', '')}"
                        body = export_data.get("body_bytes", b"")
                        if isinstance(body, bytes):
                            export_data["body_bytes"] = body.decode("utf-8", errors="replace")
                        # Remove non-serializable fields
                        export_data.pop("last_response", None)
                        f.write(json.dumps(export_data) + "\n")

                # Export to Postman collection
                eng.export_session_jsonl_to_postman(
                    self.folder,
                    collection_name=collection_name,
                    delete_temp_vars=False
                )
            except Exception as e:
                messagebox.showerror("Auto-Save Failed", f"Could not save collection:\n{e}")

        self.destroy()

    def load_collection(self):
        p = filedialog.askopenfilename(
            title="Choose Postman collection (v2.1)",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")]
        )
        if not p:
            return
        # Clear stale state before loading new collection
        self.clear_collection()
        try:
            items = eng.load_collection_items(Path(p))
            self.ctrl.load_initial_data(items)
        except Exception as e:
            messagebox.showerror("Load Collection", f"Failed to parse collection:\n{e}")
            return

        self.lst_items.delete(0, tk.END)
        self._items_data = items  # store for selection
        
        # Populate tree with folder structure (uses 'path' field from import)
        self._tree_sidebar.populate_with_folders(items)
        
        messagebox.showinfo("Load Collection", f"Loaded {len(items)} items.")
        
        # --- BEGIN ADD: sync x-apitool-extract from loaded items into sidecar ---
        try:
            idx = self._read_extractors_index()
            for it in items:
                rules = it.get("extractors") or []
                if not rules:
                    continue
                key = f"{(it.get('method') or 'GET').upper()} {it.get('url') or ''}"
                idx[key] = rules
            if items:
                self._write_extractors_index(idx)
        except Exception:
            pass
        # --- END ADD ---

        # NEW: also import top-level collection variables to temp store
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
            var_arr = data.get("variable", []) or []
            self.vars.clear()
            for v in var_arr:
                k = str(v.get("key") or v.get("name") or "").strip()
                if not k:
                    continue
                val = "" if v.get("value") is None else str(v.get("value"))
                self.vars.set(k, val)
            self.vars.save()
            if var_arr:
                messagebox.showinfo("Collection Variables", f"Imported {len(var_arr)} variable(s) into temp store.")
        except Exception:
            pass


    def on_select_item(self, _evt):
        self.ctrl.handle_selection(self)

    def _show_listbox_context_menu(self, event):
        """Handled by TreeSidebar._on_right_click now."""
        pass

    def _duplicate_request(self, idx):
        """Handled by TreeSidebar._duplicate_request now."""
        pass

    @staticmethod
    def _shlex_quote_join(parts):
        from curl_handler import _shlex_quote_join
        return _shlex_quote_join(parts)


    def copy_as_curl(self):
        from curl_handler import copy_as_curl
        copy_as_curl(self)


    def send_request(self):
        if not self.lst_items.curselection():
            from sidebar_manager import SidebarManager; SidebarManager.sync_new_request(self)

        selection = self.lst_items.curselection()
        req_index = self.ctrl.last_index if self.ctrl.last_index is not None else (selection[0] if selection else 0)

        method = self.method_var.get().upper()
        url = self.ent_url.get().strip()
        headers = self._parse_headers_from_text(self.txt_headers.get("1.0", tk.END))
        payload_text = self.txt_payload.get("1.0", tk.END)
        body = payload_text.encode("utf-8") if payload_text.strip() else b""
        if not url:
            messagebox.showwarning("Send Request", "URL is required.")
            return

        # --- Run pre-request script ---
        prerequest_script = self.txt_prerequest.get("1.0", "end-1c").strip()
        if prerequest_script:
            from pm_runtime import build_pm_context, run_script
            pm_ctx = build_pm_context(
                var_store=self.vars,
                method=method, url=url,
                req_headers=headers,
                req_body=payload_text.strip()
            )
            err, script_output = run_script(prerequest_script, pm_ctx)
            if script_output and script_output.strip():
                eng.log_block(self.logger, "PRE-REQUEST SCRIPT OUTPUT", script_output.strip().splitlines())
            if err:
                messagebox.showwarning("Pre-request Script", err)
            else:
                # Apply any mutations the script made
                method = pm_ctx.request.method or method
                url = pm_ctx.request.url or url
                headers = pm_ctx.request.headers or headers
                body = (pm_ctx.request.body or "").encode("utf-8") if pm_ctx.request.body else body

        threading.Thread(
            target=self._do_request_thread,
            args=(req_index, method, url, headers, body),
            daemon=True
        ).start()




    def _do_request_thread(self, req_index: int, method: str, url: str, headers: Dict[str, str], body: bytes):
        # Keep original (template) URL as typed by user/CSV (e.g., {{env}}/api/endpoint{{num}})
        template_url = url

        # Resolve collection variables for the actual HTTP call
        r_url, r_headers, r_body = eng._render_with_vars(self.folder, url, headers, body)

        # Send the request using the RESOLVED values
        t0 = time.perf_counter()
        status, reason, resp_headers, resp_body = eng.send_request(
            method, r_url, r_headers, r_body, timeout=60.0
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        resp_size_bytes = len(resp_body or b"")

        # --- STEP 5: PRETTY PRINT RESPONSE ---
        from response_formatter import ResponseFormatter; ui_resp_text = ResponseFormatter.format_ui_response(self, resp_body)

        # Push BOTH URLs back to the UI thread:
        self.queue.put((
            "response",
            req_index,
            method,
            template_url,         # <── index 2
            r_url,                # <── index 3
            r_headers,
            r_body,
            status,
            reason,
            resp_headers,
            resp_body,            # <── Now potentially formatted
            ui_resp_text,
            elapsed_ms,
            resp_size_bytes
        ))
        





    def _process_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                if item[0] == "response":
                    # 1. Unpack with the new 11th item (ui_resp) at the end
                    (_tag,
                     req_index,
                     method,
                     template_url,
                     resolved_url,
                     headers,
                     body,
                     status,
                     reason,
                     resp_headers,
                     resp_body,
                     ui_resp,
                     elapsed_ms,
                     resp_size_bytes) = item # <── Unpacking the formatted string
                     
                    
                    # --- BEGIN MOD: remember last request & response context ---
                    self._last_method = method or (getattr(self, "method_var", None) and self.method_var.get()) or "GET"
                    self._last_template_url = template_url or (getattr(self, "ent_url", None) and self.ent_url.get()) or ""
                    self._last_resp_headers = dict(resp_headers or {})
                    
                    # This line no longer crashes because resp_body is still bytes
                    self._last_resp_body_bytes = bytes(resp_body or b"")
                    try:
                        self._last_resp_elapsed_ms = float(elapsed_ms)
                    except Exception:
                        self._last_resp_elapsed_ms = None
                    try:
                        self._last_resp_size_bytes = int(resp_size_bytes)
                    except Exception:
                        self._last_resp_size_bytes = None
                    # --- END MOD ---
                    
                    
                    # --- BEGIN ADD: enable button only after real response ---
                    try:
                        if hasattr(self, "btn_set_collect_vars"):
                            self.btn_set_collect_vars.state(["!disabled"])
                    except Exception:
                        pass
                    # --- END ADD ---


                    # 1) Show/log the RESOLVED URL
                    # Note: We still pass resp_body here, but the formatter inside 
                    # _show_request_response will likely use self._last_resp_body_text
                    self._show_request_response(
                        method, resolved_url, headers, body, status, reason, resp_headers, ui_resp,
                        elapsed_ms=self._last_resp_elapsed_ms,
                        size_bytes=self._last_resp_size_bytes
                    )
                    self._flash_response()

                    # --- Run post-response (Tests) script ---
                    try:
                        test_script = self.txt_tests.get("1.0", "end-1c").strip()
                        if test_script:
                            from pm_runtime import build_pm_context, run_script
                            resp_body_text = (resp_body or b"").decode("utf-8", errors="replace")
                            pm_ctx = build_pm_context(
                                var_store=self.vars,
                                status=status,
                                resp_headers=resp_headers,
                                resp_body=resp_body_text,
                                method=method,
                                url=resolved_url,
                                req_headers=headers,
                                req_body=(body or b"").decode("utf-8", errors="replace")
                            )
                            err, script_output = run_script(test_script, pm_ctx)
                            if script_output and script_output.strip():
                                eng.log_block(self.logger, "TESTS SCRIPT OUTPUT", script_output.strip().splitlines())
                            if err:
                                messagebox.showwarning("Tests Script", err)
                    except Exception as e:
                        messagebox.showwarning("Tests Script", f"Script error: {e}")

                    try:
                        if isinstance(req_index, int) and 0 <= req_index < len(self.ctrl.requests):
                            self.ctrl.requests[req_index]["last_response"] = {
                                "status": status,
                                "reason": reason,
                                "headers": dict(resp_headers or {}),
                                "body_text": ui_resp if isinstance(ui_resp, str) else "",
                                "elapsed_ms": self._last_resp_elapsed_ms,
                                "size_bytes": self._last_resp_size_bytes,
                            }
                    except Exception:
                        pass
                    
                    
                    # --- BEGIN ADD: apply per-request extractors ---
                    try:
                        eng.apply_extractors_and_save(
                            folder=self.folder,
                            method=method,
                            template_url=template_url,
                            status=status,
                            headers=resp_headers,
                            resp_body=resp_body,
                            logger=self.logger
                        )
                    except Exception as e:
                        try:
                            self.logger and eng.log_block(self.logger, "EXTRACTORS", [f"Error: {e}"])
                        except Exception:
                            pass
                    # --- END ADD ---


                    # 2) Append to session with the TEMPLATE URL
                    eng.append_request_to_session(
                        self.folder,
                        method,
                        template_url,
                        headers,
                        body.decode("utf-8", errors="replace")
                    )
                    
                    # Run extractors again for TempVarStore
                    eng.apply_extractors_and_save(
                        folder=self.folder,
                        method=method,
                        template_url=template_url,
                        status=status,
                        headers=resp_headers,
                        resp_body=resp_body,
                        logger=self.logger
                    )

                    
                    # Cache for "Set Collection Variables" dialog
                    self._last_method = method
                    
                    # --- BEGIN MOD: robust capture of last request identifiers ---
                    self._last_method = method or (self.method_var.get() if hasattr(self, "method_var") else "GET")
                    self._last_template_url = (
                        template_url
                        or (self.ent_url.get() if hasattr(self, "ent_url") else "")
                    )
                    # --- END MOD ---

                    self._last_resp_headers = dict(resp_headers or {})
                    
                    # 2. Use the PRETTY string (ui_resp) for the UI text display
                    self._last_resp_body_text = ui_resp if ui_resp else ""
                    
                    
                    # Clear large buffers
                    body = b""
                    resp_body = b""
                    ui_resp = ""
        except queue.Empty:
            pass
        self.after(100, self._process_queue)


    # --- BEGIN ADD: extractor sidecar helpers ---
    #_EXTRACTORS_INDEX_FILENAME = "extractors.index.json"

    def _read_extractors_index(self) -> dict:
        p = (self.folder / _EXTRACTORS_INDEX_FILENAME)
        try:
            if p.exists():
                return json.loads(p.read_text(encoding="utf-8")) or {}
        except Exception:
            pass
        return {}

    def _write_extractors_index(self, data: dict) -> None:
        try:
            (self.folder / _EXTRACTORS_INDEX_FILENAME).write_text(
                json.dumps(data, indent=2), encoding="utf-8"
            )
        except Exception as e:
            messagebox.showerror("Extractors", f"Failed to save extractors:\n{e}")
    # --- END ADD: extractor sidecar helpers ---


    def export_session(self):
        from export_handler import ExportHandler; ExportHandler.run_export(self, eng)

    def toggle_ssl(self):
        eng.set_disable_ssl(not eng.DISABLE_SSL)
        self._update_ssl_label()

    def toggle_redirects(self):
        eng.set_follow_redirects(not eng.FOLLOW_REDIRECTS)
        self._update_redirects_label()

    # ---------------------------- Variables Dialog (NEW) ----------------------



    def open_vars_dialog(self):
        win = tk.Toplevel(self)
        win.title("Collection Variables (temp)")
        win.transient(self)
        win.grab_set()

        frm = ttk.Frame(win)
        frm.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        ttk.Label(frm, text="Variables (Key: Value per line)").pack(anchor="w")

        txt = tk.Text(frm, height=18)
        txt.pack(fill=tk.BOTH, expand=True)
        # Alternating line colors (same as headers)
        txt.tag_configure("even_line", background="#c8e6c9")
        txt.tag_configure("odd_line", background="#f5f9ff")

        def _colorize_vars(*_):
            txt.tag_remove("even_line", "1.0", tk.END)
            txt.tag_remove("odd_line", "1.0", tk.END)
            line_count = int(txt.index("end-1c").split(".")[0])
            for i in range(1, line_count + 1):
                tag = "even_line" if i % 2 == 0 else "odd_line"
                txt.tag_add(tag, f"{i}.0", f"{i}.end")
            try:
                txt.edit_modified(False)
            except Exception:
                pass

        txt.bind("<KeyRelease>", _colorize_vars)
        txt.bind("<<Modified>>", _colorize_vars)

        # Load variables into key: value format
        self.vars.load()
        for k, v in self.vars.items():
            txt.insert(tk.END, f"{k}: {v}\n")
        _colorize_vars()

        def save():
            raw = txt.get("1.0", tk.END).strip()

            new_vars = {}
            if raw:
                for line in raw.splitlines():
                    line = line.strip()
                    if not line: 
                        continue
                    if ":" not in line:
                        messagebox.showerror("Error", f"Invalid line (expected key: value):\n{line}")
                        return
                    key, value = line.split(":", 1)
                    key = key.strip()
                    value = value.strip()
                    if key:
                        new_vars[key] = value

            self.vars.clear()
            for k, v in new_vars.items():
                self.vars.set(k, v)
            self.vars.save()

            messagebox.showinfo("Variables", "Saved.")

        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, pady=6)

        def save_and_close():
            save()
            win.destroy()

        ttk.Button(btns, text="Save", command=save).pack(side=tk.LEFT)
        ttk.Button(btns, text="Save & Close", command=save_and_close).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btns, text="Close", command=win.destroy).pack(side=tk.RIGHT)


    # --- BEGIN ADD: Set Collection Variables dialog ---
    def open_set_collect_vars_dialog(self):
        # Preconditions
        if not getattr(self, "_last_template_url", None) or not getattr(self, "_last_method", None):
            messagebox.showwarning("Set Collection Variables", "Send a request first to capture from its response.")
            return
        
                # --- BEGIN MOD: robust precondition with safe fallbacks ---
        last_method = getattr(self, "_last_method", None) or (self.method_var.get() if hasattr(self, "method_var") else None)
        last_template_url = getattr(self, "_last_template_url", None) or (self.ent_url.get() if hasattr(self, "ent_url") else None)

        # We do need at least some response to capture from; check stored body bytes
        last_body_bytes = getattr(self, "_last_resp_body_bytes", None)
        last_headers = getattr(self, "_last_resp_headers", None)

        # If we truly have no response material, warn.
        if not last_body_bytes and not last_headers:
            messagebox.showwarning("Set Collection Variables", "Send a request first to capture from its response.")
            return

        # Rebind locals used later in the dialog code
        self._last_method = last_method or "GET"
        self._last_template_url = last_template_url or ""
        # --- END MOD ---

        # Parse JSON body if possible
        body_text = ""
        try:
            body_text = (self._last_resp_body_bytes or b"").decode("utf-8", errors="replace")
        except Exception:
            body_text = ""
        candidates_json_paths = []
        payload_obj = None
        try:
            payload_obj = json.loads(body_text) if body_text.strip() else None
        except Exception:
            payload_obj = None

        def _walk(obj, path, limit=500):
            # simple enumerator for JSON Pointer-like "$" paths
            if len(candidates_json_paths) >= limit:
                return
            candidates_json_paths.append(path)
            if isinstance(obj, dict):
                for k, v in list(obj.items())[:1000]:
                    _walk(v, f"{path}.{k}", limit)
            elif isinstance(obj, list):
                for i, v in enumerate(obj[:200]):
                    _walk(v, f"{path}[{i}]", limit)

        if isinstance(payload_obj, (dict, list)):
            _walk(payload_obj, "$")

        # Headers candidates
        header_keys = sorted((self._last_resp_headers or {}).keys(), key=str.lower)

        # Dialog
        win = tk.Toplevel(self)
        win.title("Set Collection Variables (per request)")
        win.transient(self); win.grab_set()

        frm = ttk.Frame(win); frm.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # Source selector
        src_var = tk.StringVar(value="json")
        ttk.Label(frm, text="Source").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(frm, text="JSON body", variable=src_var, value="json").grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(frm, text="Header",    variable=src_var, value="header").grid(row=0, column=2, sticky="w")

        # JSON paths list
        ttk.Label(frm, text="JSON paths (click to choose)").grid(row=1, column=0, columnspan=3, sticky="w", pady=(8,0))
        lst_json = tk.Listbox(frm, height=10)
        lst_json.grid(row=2, column=0, columnspan=3, sticky="nsew")
        for p in candidates_json_paths:
            lst_json.insert(tk.END, p)

        # Headers list
        ttk.Label(frm, text="Headers (click to choose)").grid(row=3, column=0, columnspan=3, sticky="w", pady=(8,0))
        lst_hdr = tk.Listbox(frm, height=8)
        lst_hdr.grid(row=4, column=0, columnspan=3, sticky="nsew")
        for hk in header_keys:
            lst_hdr.insert(tk.END, hk)

        # Variable name + chosen path/key
        ttk.Label(frm, text="Variable name ({{var}})").grid(row=5, column=0, sticky="w", pady=(8,0))
        ent_var = ttk.Entry(frm, width=30); ent_var.grid(row=5, column=1, columnspan=2, sticky="we")

        ttk.Label(frm, text="Chosen path / header key").grid(row=6, column=0, sticky="w", pady=(8,0))
        ent_sel = ttk.Entry(frm, width=60); ent_sel.grid(row=6, column=1, columnspan=2, sticky="we")

        def on_pick_json(evt=None):
            try:
                sel = lst_json.get(lst_json.curselection())
                src_var.set("json")
                ent_sel.delete(0, tk.END); ent_sel.insert(0, sel)
                # suggest var name from last token
                last = sel.split(".")[-1].split("[")[0].strip("$") or "value"
                ent_var.delete(0, tk.END); ent_var.insert(0, last)
            except Exception:
                pass

        def on_pick_hdr(evt=None):
            try:
                sel = lst_hdr.get(lst_hdr.curselection())
                src_var.set("header")
                ent_sel.delete(0, tk.END); ent_sel.insert(0, sel)
                ent_var.delete(0, tk.END); ent_var.insert(0, sel.lower().replace("-", "_"))
            except Exception:
                pass

        lst_json.bind("<<ListboxSelect>>", on_pick_json)
        lst_hdr.bind("<<ListboxSelect>>", on_pick_hdr)

        # Buttons
        btns = ttk.Frame(frm); btns.grid(row=7, column=0, columnspan=3, sticky="we", pady=10)
        def on_save():
            var_name = ent_var.get().strip()
            sel = ent_sel.get().strip()
            src = src_var.get().strip()
            if not var_name or not sel:
                messagebox.showerror("Set Collection Variables", "Choose a path/header and enter a variable name.")
                return
            # Build rule
            if src == "json":
                rule = {"name": var_name, "from": "json", "path": sel}
            else:
                rule = {"name": var_name, "from": "header", "key": sel}

            # Persist to sidecar by (METHOD + TEMPLATE_URL)

            # --- BEGIN MOD: compute stable key + show debug if invalid ---
            method = getattr(self, "_last_method", None) or "GET"
            tmpl   = getattr(self, "_last_template_url", None) or ""

            key = f"{method.upper()} {tmpl}".strip()

            if not tmpl:
                messagebox.showerror("Set Collection Variables", "Template URL was empty. Send a request again.")
                return

            idx = self._read_extractors_index()
            rules = idx.get(key, [])

            # remove old rule with same name
            rules = [r for r in rules if r.get("name") != var_name]

            rules.append(rule)
            idx[key] = rules

            self._write_extractors_index(idx)

            messagebox.showinfo("Set Collection Variables", f"Saved for:\n{key}\n→ {rule}")
            # --- END MOD ---
            win.destroy()

        ttk.Button(btns, text="Save", command=on_save).pack(side=tk.LEFT)
        ttk.Button(btns, text="Close", command=win.destroy).pack(side=tk.RIGHT)

        # grid weights
        frm.rowconfigure(2, weight=1)
        frm.rowconfigure(4, weight=1)
        frm.columnconfigure(2, weight=1)
    # --- END ADD: Set Collection Variables dialog ---



    def open_set_vars_dialog(self):
        # Require a response first
        if not (self._last_resp_body_text or self._last_resp_headers):
            messagebox.showwarning("Set Collection Variables", "Send a request first to capture values.")
            return
        dlg = tk.Toplevel(self); dlg.title("Set Collection Variables"); dlg.transient(self); dlg.grab_set()
        frm = ttk.Frame(dlg); frm.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        # Tabs: JSON Body / Headers
        nb = ttk.Notebook(frm); nb.pack(fill=tk.BOTH, expand=True)
        tab_body = ttk.Frame(nb); tab_hdr = ttk.Frame(nb)
        nb.add(tab_body, text="Body (JSON)"); nb.add(tab_hdr, text="Headers")

        # Body viewer + quick path picker (minimal: click-to-copy JSON Pointer)
        txt_body = tk.Text(tab_body, height=18); txt_body.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        try:
            pretty = json.dumps(json.loads(self._last_resp_body_text or "{}"), indent=2, ensure_ascii=False)
        except Exception:
            pretty = (self._last_resp_body_text or "").strip() or "(non-JSON / empty)"
        txt_body.insert(tk.END, pretty); txt_body.config(state=tk.DISABLED)

        # Header list
        hdr_list = tk.Listbox(tab_hdr, height=12)
        hdr_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        for k, v in (self._last_resp_headers or {}).items():
            hdr_list.insert(tk.END, f"{k}: {v}")

        # Selection inputs
        row = ttk.Frame(frm); row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(row, text="Source:").grid(row=0, column=0, sticky="w")
        src_var = tk.StringVar(value="json")
        ttk.Radiobutton(row, text="JSON path ($.a.b or $.arr[0])", variable=src_var, value="json").grid(row=0, column=1, sticky="w", padx=6)
        ttk.Radiobutton(row, text="Header key", variable=src_var, value="header").grid(row=0, column=2, sticky="w", padx=6)

        row2 = ttk.Frame(frm); row2.pack(fill=tk.X, pady=6)
        ttk.Label(row2, text="JSON path / Header key:").grid(row=0, column=0, sticky="w")
        ent_key = ttk.Entry(row2, width=50); ent_key.grid(row=0, column=1, sticky="we", padx=6)
        row2.columnconfigure(1, weight=1)

        row3 = ttk.Frame(frm); row3.pack(fill=tk.X, pady=6)
        ttk.Label(row3, text="Variable name ({{var}}):").grid(row=0, column=0, sticky="w")
        ent_var = ttk.Entry(row3, width=32); ent_var.grid(row=0, column=1, sticky="w", padx=6)

        # Quick helpers: double-click JSON text to suggest a path; double-click header to fill key
        def suggest_from_header(_evt):
            sel = hdr_list.curselection()
            if not sel: return
            line = hdr_list.get(sel[0])
            k = line.split(":", 1)[0].strip()
            src_var.set("header"); ent_key.delete(0, tk.END); ent_key.insert(0, k)
            # auto-suggest variable name
            ent_var.delete(0, tk.END); ent_var.insert(0, k.lower().replace("-", "_"))

        hdr_list.bind("<Double-Button-1>", suggest_from_header)

        # Save rule → delegate to engine (per-request association)
        btns = ttk.Frame(frm); btns.pack(fill=tk.X, pady=(8, 0))
        def on_save():
            key = ent_key.get().strip()
            var = ent_var.get().strip()
            if not key or not var:
                messagebox.showerror("Set Collection Variables", "Enter both the path/key and variable name.")
                return
            rule = {"name": var}
            if src_var.get() == "json":
                rule.update({"from": "json", "path": key})
            else:
                rule.update({"from": "header", "key": key})

            try:
                # Prefer binding to a collection item if available, else to the template URL signature
                eng.add_request_extractor(
                    folder=self.folder,
                    item_path=self._last_item_path,
                    method=self._last_method,
                    template_url=self._last_template_url,
                    rule=rule
                )
                messagebox.showinfo("Set Collection Variables", f"Saved mapping: {key} → {{ {var} }}")
                dlg.destroy()
            except Exception as e:
                messagebox.showerror("Set Collection Variables", f"Failed to save mapping:\n{e}")

        ttk.Button(btns, text="Save", command=on_save).pack(side=tk.LEFT)
        ttk.Button(btns, text="Close", command=dlg.destroy).pack(side=tk.RIGHT)



    # ---------------------------- Batch Run (delegated to batch_runner.py) ----
    _PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")

    def _extract_placeholders(self, *texts: str) -> set:
        from batch_runner import _extract_placeholders
        return _extract_placeholders(self, *texts)

    def _render_template(self, text: str, ctx: dict) -> str:
        from batch_runner import _render_template
        return _render_template(self, text, ctx)

    def _reset_progress(self):
        from batch_runner import _reset_progress
        _reset_progress(self)

    def _update_progress_label(self, text: str):
        from batch_runner import _update_progress_label
        _update_progress_label(self, text)

    def _increment_progress(self):
        from batch_runner import _increment_progress
        _increment_progress(self)

    def _series_runner_same(self, n: int, delay_ms: int, method: str, url: str, headers: dict, body: bytes):
        from batch_runner import _series_runner_same
        _series_runner_same(self, n, delay_ms, method, url, headers, body)

    def _parallel_runner_same(self, n: int, workers: int, method: str, url: str, headers: dict, body: bytes):
        from batch_runner import _parallel_runner_same
        _parallel_runner_same(self, n, workers, method, url, headers, body)

    def _series_runner_csv(self, rows: List[Dict[str, str]], method: str,
                           url_tmpl: str, headers_tmpl: str, body_tmpl: str, delay_ms: int):
        from batch_runner import _series_runner_csv
        _series_runner_csv(self, rows, method, url_tmpl, headers_tmpl, body_tmpl, delay_ms)

    def open_run_collection_n_dialog(self):
        from batch_runner import open_run_collection_n_dialog
        open_run_collection_n_dialog(self)

    def run_collection_n_times(self, n: int, delay_ms: int = 0):
        from batch_runner import run_collection_n_times
        run_collection_n_times(self, n, delay_ms)

    def open_run_collection_delay_dialog(self):
        from batch_runner import open_run_collection_delay_dialog
        open_run_collection_delay_dialog(self)

    def run_collection_series_now(self, delay_ms: int = 0):
        from batch_runner import run_collection_series_now
        run_collection_series_now(self, delay_ms)

    def _start_batch_run(self, source: str, mode: str, n: int, delay_ms: int, workers: int,
                         csv_path: Optional[Path], dlg: tk.Toplevel):
        from batch_runner import _start_batch_run
        _start_batch_run(self, source, mode, n, delay_ms, workers, csv_path, dlg)

    def open_run_dialog(self):
        from batch_runner import open_run_dialog
        open_run_dialog(self)

    def open_selective_run_dialog(self):
        from batch_runner import open_selective_run_dialog
        open_selective_run_dialog(self)

if __name__ == "__main__":
    app = ApiGuiApp()
    app.mainloop()
