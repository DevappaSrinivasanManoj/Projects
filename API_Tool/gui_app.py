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
        self.folder = Path("artifacts").resolve()
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
        self._build_menu()
        self._build_layout()
        self._update_ssl_label()
        self.bind_all("<Control-f>", self._on_ctrl_f)

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

        main = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        left = ttk.Frame(main, width=340)
        main.add(left, weight=1)

        right = ttk.Frame(main)
        main.add(right, weight=4)

        frm_coll = ttk.LabelFrame(left, text="Collection Items")
        frm_coll.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.lst_items = tk.Listbox(frm_coll)
        self.lst_items.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        from collection_editor import CollectionEditor; CollectionEditor.inject_controls(self, frm_coll)
        self.lst_items.bind("<<ListboxSelect>>", self.on_select_item)

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
        ttk.Button(row1_inner, text="Send", command=self.send_request).grid(row=0, column=1, sticky="e", padx=(8, 0))
        frm_req.columnconfigure(1, weight=1)
        frm_req.columnconfigure(3, weight=1)

        row_btns = ttk.Frame(frm_req)
        row_btns.grid(row=2, column=0, columnspan=4, sticky="we", padx=4, pady=(0, 4))
        row_btns.columnconfigure(0, weight=1)

        left_actions = ttk.Frame(row_btns)
        left_actions.grid(row=0, column=0, sticky="w")
        ttk.Button(left_actions, text="Copy as cURL", command=self.copy_as_curl).pack(side=tk.LEFT)
        ttk.Button(left_actions, text="Paste cURL...", command=self.open_curl_popup).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(left_actions, text="Load Postman Collection...", command=self.load_collection).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(left_actions, text="Run...", command=self.open_run_dialog).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(left_actions, text="Cancel Run", command=lambda: setattr(self, "_batch_cancelled", True)).pack(side=tk.LEFT, padx=(8, 0))

        right_actions = ttk.Frame(row_btns)
        right_actions.grid(row=0, column=1, sticky="e")

        self.validate_schema_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(right_actions, text="Validate schema", variable=self.validate_schema_var).pack(side=tk.LEFT)
        ttk.Checkbutton(
            right_actions, text="Compare", variable=self.compare_var, command=self._on_compare_toggled
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(right_actions, text="Set Collection Variables", command=self.open_set_collect_vars_dialog).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(right_actions, text="Run Collection (All)", command=self.run_collection_series_now).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(right_actions, text="Run N Times...", command=self.open_run_collection_n_dialog).pack(side=tk.LEFT, padx=(8, 0))

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

        tab_body = ttk.Frame(req_tabs)
        req_tabs.add(tab_body, text="Body")
        btns = ttk.Frame(tab_body)
        btns.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=(0, 4))
        ttk.Button(btns, text="Validate JSON", command=self.validate_json).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Pretty JSON", command=self.pretty_json).pack(side=tk.LEFT, padx=2)
        ttk.Button(btns, text="Clear Body", command=lambda: self.txt_payload.delete("1.0", tk.END)).pack(side=tk.LEFT, padx=2)

        self.txt_payload = tk.Text(tab_body)
        self.txt_payload.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 2))

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
        self.open_response_search()

    def _get_active_response_text_widget(self) -> Optional[tk.Text]:
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

    def open_response_search(self):
        if getattr(self, "_search_win", None) is not None:
            try:
                self._search_win.lift()
                self._search_ent.focus_set()
                return
            except Exception:
                self._search_win = None

        win = tk.Toplevel(self)
        win.title("Find (Response)")
        win.geometry("520x120")
        self._search_win = win

        row = ttk.Frame(win)
        row.pack(fill=tk.X, padx=10, pady=10)
        ttk.Label(row, text="Find:").pack(side=tk.LEFT)
        ent = ttk.Entry(row)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
        self._search_ent = ent

        row2 = ttk.Frame(win)
        row2.pack(fill=tk.X, padx=10, pady=(0, 10))

        def clear_highlight(txt: tk.Text):
            try:
                txt.tag_remove("search_hit", "1.0", tk.END)
            except Exception:
                pass

        def highlight_at(txt: tk.Text, start: str, end: str):
            clear_highlight(txt)
            try:
                txt.tag_add("search_hit", start, end)
                txt.tag_config("search_hit", background="#fff59d")
                txt.see(start)
                txt.mark_set("insert", end)
            except Exception:
                pass

        def find_next():
            txt = self._get_active_response_text_widget()
            if txt is None:
                return
            q = ent.get()
            if not q:
                return
            start = txt.index("insert")
            idx = txt.search(q, start, stopindex=tk.END, nocase=True)
            if not idx:
                idx = txt.search(q, "1.0", stopindex=tk.END, nocase=True)
            if idx:
                end = f"{idx}+{len(q)}c"
                highlight_at(txt, idx, end)

        def find_prev():
            txt = self._get_active_response_text_widget()
            if txt is None:
                return
            q = ent.get()
            if not q:
                return
            start = txt.index("insert")
            idx = txt.search(q, start, stopindex="1.0", backwards=True, nocase=True)
            if not idx:
                idx = txt.search(q, tk.END, stopindex="1.0", backwards=True, nocase=True)
            if idx:
                end = f"{idx}+{len(q)}c"
                highlight_at(txt, idx, end)

        ttk.Button(row2, text="Prev", command=find_prev).pack(side=tk.LEFT)
        ttk.Button(row2, text="Next", command=find_next).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(row2, text="Close", command=win.destroy).pack(side=tk.RIGHT)

        def on_close():
            try:
                txt = self._get_active_response_text_widget()
                if txt is not None:
                    clear_highlight(txt)
            except Exception:
                pass
            self._search_win = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)
        win.transient(self)
        win.grab_set()
        ent.focus_set()

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
        try:
            obj = json.loads(raw)
            self.txt_payload.delete("1.0", tk.END)
            self.txt_payload.insert(tk.END, json.dumps(obj, indent=2))
        except json.JSONDecodeError:
            messagebox.showwarning("Pretty JSON", "Payload is not valid JSON; showing raw unchanged.")

    def open_curl_popup(self):
        win = tk.Toplevel(self)
        win.title("Paste cURL")
        win.geometry("900x420")

        txt = tk.Text(win, height=12)
        txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.txt_curl = txt

        def _on_close():
            try:
                if getattr(self, "txt_curl", None) is txt:
                    self.txt_curl = None
            except Exception:
                pass
            win.destroy()

        btns = ttk.Frame(win)
        btns.pack(fill=tk.X, padx=8, pady=(0, 8))
        ttk.Button(btns, text="Parse cURL", command=self.parse_curl).pack(side=tk.LEFT)
        ttk.Button(btns, text="Close", command=_on_close).pack(side=tk.RIGHT)

        win.protocol("WM_DELETE_WINDOW", _on_close)
        win.transient(self)
        win.grab_set()
        txt.focus_set()

    def parse_curl(self):
        txt = getattr(self, "txt_curl", None)
        if txt is None:
            messagebox.showwarning("Parse cURL", "Open Paste cURL... first.")
            return
        curl_cmd = txt.get("1.0", tk.END).strip()
        if not curl_cmd:
            messagebox.showwarning("Parse cURL", "Please paste a cURL command.")
            return
        try:
            method, url, headers, body = eng.parse_curl(curl_cmd, folder=self.folder)
        except Exception as e:
            messagebox.showerror("Parse cURL", f"Failed to parse cURL: {e}")
            return
        self.method_var.set(method)
        self.ent_url.delete(0, tk.END)
        self.ent_url.insert(0, url)
        self.txt_headers.delete("1.0", tk.END)
        if headers:
            self.txt_headers.insert(tk.END, json.dumps(headers, indent=2))
        self.txt_payload.delete("1.0", tk.END)
        if body:
            try:
                self.txt_payload.insert(tk.END, body.decode("utf-8"))
            except Exception:
                self.txt_payload.insert(tk.END, "[binary payload]")
        messagebox.showinfo("Parse cURL", "Parsed and populated the request builder.")


    def load_collection(self):
        p = filedialog.askopenfilename(
            title="Choose Postman collection (v2.1)",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")]
        )
        if not p:
            return
        try:
            items = eng.load_collection_items(Path(p))
            self.ctrl.load_initial_data(items)
        except Exception as e:
            messagebox.showerror("Load Collection", f"Failed to parse collection:\n{e}")
            return

        self.lst_items.delete(0, tk.END)
        self._items_data = items  # store for selection
        
        # --- FIXED LOOP: Prioritize the 'name' field ---
        for it in items:
            name = it.get("name")
            if name and name.strip():
                # If a custom name exists, show ONLY that name
                display_text = name.strip()
            else:
                # Fallback: only show method and URL if name is missing
                display_text = f"{it['method']:6s} {it['url']}"
            
            self.lst_items.insert(tk.END, display_text)
        
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

    @staticmethod
    def _shlex_quote_join(parts):
        def shlex_quote(s: str) -> str:
            if not s:
                return "''"
            safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._/:?&=%")
            if all(ch in safe for ch in s):
                return s
            return "'" + s.replace("'", "'\\''") + "'"
        return " ".join(shlex_quote(p) for p in parts)


    def copy_as_curl(self):
        method = self.method_var.get().upper()
        url = self.ent_url.get().strip()
        headers = self._parse_headers_from_text(self.txt_headers.get("1.0", tk.END))
        body_text = self.txt_payload.get("1.0", tk.END)
        body = body_text.encode("utf-8") if body_text.strip() else b""

        # NEW: resolve collection variables for curl output
        r_url, r_headers, r_body = eng._render_with_vars(self.folder, url, headers, body)

        parts = ["curl"]
        if method and method != "GET":
            parts += ["-X", method]
        for k, v in r_headers.items():
            parts += ["-H", f"{k}: {v}"]
        if r_body:
            try:
                parts += ["--data-raw", r_body.decode("utf-8").strip()]
            except Exception:
                pass
        parts.append(r_url)

        curl_str = self._shlex_quote_join(parts)
        self.clipboard_clear()
        self.clipboard_append(curl_str)
        messagebox.showinfo("Copy as cURL", "cURL command copied to clipboard.")


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

        # Load variables into key: value format
        self.vars.load()
        for k, v in self.vars.items():
            txt.insert(tk.END, f"{k}: {v}\n")

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

        ttk.Button(btns, text="Save", command=save).pack(side=tk.LEFT)
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



    # ---------------------------- Batch Run (unchanged logic; trimmed) --------
    _PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")

    def _extract_placeholders(self, *texts: str) -> set:
        keys = set()
        for t in texts:
            if not t:
                continue
            tmp = t.replace("{{{{", "\uE000").replace("}}}}", "\uE001")
            for m in self._PLACEHOLDER_RE.finditer(tmp):
                keys.add(m.group(1))
        return keys


    def _render_template(self, text: str, ctx: dict) -> str:
        """
        CSV templating: replace only placeholders that EXIST in ctx.
        If a key is missing (e.g., {{env}}), LEAVE IT AS-IS so that
        the collection-variable renderer can resolve it later.
        Supports brace escapes: '{{{{' -> '{', '}}}}' -> '}'.
        """
        if not text:
            return text
        s = text.replace("{{{{", "\uE000").replace("}}}}", "\uE001")

        def repl(m):
            key = m.group(1)
            if key in ctx:
                return str(ctx[key])
            # KEEP UNKNOWN PLACEHOLDERS
            return m.group(0)

        s = self._PLACEHOLDER_RE.sub(repl, s)
        return s.replace("\uE000", "{").replace("\uE001", "}")


    def _reset_progress(self):
        self._batch_running = False
        self._batch_cancelled = False
        self._batch_total = 0
        self._batch_completed = 0
        self._parallel_executor = None
        self._parallel_prev_compare_state = None
        self._update_progress_label("")

    def _update_progress_label(self, text: str):
        try:
            self.lbl_progress.config(text=text)
        except Exception:
            pass

    def _increment_progress(self):
        self._batch_completed += 1
        self._update_progress_label(f"{self._batch_completed}/{self._batch_total}")
        if self._batch_completed >= self._batch_total:
            if self._parallel_prev_compare_state is not None:
                try:
                    self.compare_var.set(self._parallel_prev_compare_state)
                except Exception:
                    pass
            self._parallel_prev_compare_state = None
            self._batch_running = False

    def _series_runner_same(self, n: int, delay_ms: int, method: str, url: str, headers: dict, body: bytes):
        selection = self.lst_items.curselection()
        req_index = self.ctrl.last_index if self.ctrl.last_index is not None else (selection[0] if selection else 0)
        for i in range(n):
            if self._batch_cancelled:
                break
            self._do_request_thread(req_index, method, url, dict(headers), body)
            self.after(0, self._increment_progress)
            if i < n - 1 and delay_ms > 0:
                time.sleep(max(0, delay_ms) / 1000.0)

    def _parallel_runner_same(self, n: int, workers: int, method: str, url: str, headers: dict, body: bytes):
        selection = self.lst_items.curselection()
        req_index = self.ctrl.last_index if self.ctrl.last_index is not None else (selection[0] if selection else 0)
        self._parallel_prev_compare_state = bool(self.compare_var.get())
        try:
            self.compare_var.set(False)
        except Exception:
            pass
        workers = max(1, int(workers or 1))
        self._parallel_executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="apigui-par")
        futures = []
        try:
            for _ in range(n):
                if self._batch_cancelled:
                    break
                fut = self._parallel_executor.submit(self._do_request_thread, req_index, method, url, dict(headers), body)
                futures.append(fut)
                fut.add_done_callback(lambda _f: self.after(0, self._increment_progress))
        finally:
            if self._batch_cancelled:
                try:
                    self._parallel_executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    self._parallel_executor.shutdown(wait=False)
                self._parallel_executor = None
            else:
                self._parallel_executor.shutdown(wait=True)
                self._parallel_executor = None

    def _series_runner_csv(self, rows: List[Dict[str, str]], method: str,
                           url_tmpl: str, headers_tmpl: str, body_tmpl: str, delay_ms: int):
        selection = self.lst_items.curselection()
        req_index = self.ctrl.last_index if self.ctrl.last_index is not None else (selection[0] if selection else 0)
        header = list(rows[0].keys()) if rows else []
        for i, row in enumerate(rows, start=1):
            if self._batch_cancelled:
                break
            ctx = {k: ("" if row.get(k) is None else str(row.get(k))) for k in header}
            url = self._render_template(url_tmpl, ctx).strip()
            hdrs_text = self._render_template(headers_tmpl, ctx)
            body_text = self._render_template(body_tmpl, ctx)
            headers = self._parse_headers_from_text(hdrs_text)
            body = body_text.encode("utf-8") if body_text.strip() else b""
            url, headers, body = eng._render_with_vars(self.folder, url, headers, body)
            self._do_request_thread(req_index, method, url, headers, body)
            self.after(0, self._increment_progress)
            if i < self._batch_total and delay_ms > 0:
                time.sleep(max(0, delay_ms) / 1000.0)



    # --- BEGIN ADD: Dialog for entering N for running collection N times ---
    def open_run_collection_n_dialog(self):
        if not hasattr(self, "_items_data") or not self._items_data:
            messagebox.showwarning("Run N Times", "No collection loaded.")
            return

        win = tk.Toplevel(self)
        win.title("Run Collection N Times")
        win.transient(self); win.grab_set()

        ttk.Label(win, text="How many times?").pack(padx=10, pady=10)
        n_var = tk.StringVar(value="1")
        ent = ttk.Entry(win, textvariable=n_var, width=10)
        ent.pack(padx=10, pady=5)

        def on_start():
            try:
                n = int(n_var.get())
                if n <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Run N Times", "Enter a valid positive number.")
                return
            win.destroy()
            self.run_collection_n_times(n)

        ttk.Button(win, text="Start", command=on_start).pack(padx=10, pady=10)
    # --- END ADD ---



    # --- BEGIN ADD: Run full collection N times ---
    def run_collection_n_times(self, n: int):
        """Runs the entire collection N times using the existing series runner."""
        if not hasattr(self, "_items_data") or not self._items_data:
            messagebox.showwarning("Run Collection", "No collection loaded.")
            return

        # Total requests to run = items_count * n
        total_items = len(self._items_data)
        total_runs = total_items * n

        if self._batch_running:
            messagebox.showwarning("Run Collection", "Another batch is already active.")
            return

        # init existing batch state
        self._batch_running = True
        self._batch_cancelled = False
        self._batch_total = total_runs
        self._batch_completed = 0
        self._update_progress_label(f"0/{total_runs}")

        try:
            self._parallel_prev_compare_state = bool(self.compare_var.get())
            self.compare_var.set(False)
        except Exception:
            self._parallel_prev_compare_state = None

        items = list(self.ctrl.requests or [])

        def _runner():
            try:
                for _ in range(n):
                    if self._batch_cancelled:
                        break
                    for req_index, it in enumerate(items):
                        if self._batch_cancelled:
                            break
                        method = (it.get("method") or "GET").upper()
                        tmpl_url = it.get("url") or ""
                        headers = dict(it.get("headers") or {})
                        body = it.get("body_bytes") or b""

                        r_url, r_headers, r_body = eng._render_with_vars(self.folder, tmpl_url, headers, body)
                        self._do_request_thread(req_index, method, tmpl_url, r_headers, r_body)

                        self.after(0, self._increment_progress)
            finally:
                def _done_ui():
                    if self._parallel_prev_compare_state is not None:
                        try:
                            self.compare_var.set(self._parallel_prev_compare_state)
                        except Exception:
                            pass
                    self._parallel_prev_compare_state = None
                    self._batch_running = False
                self.after(0, _done_ui)

        threading.Thread(target=_runner, daemon=True).start()
    # --- END ADD ---


    # --- BEGIN ADD: series runner for entire collection ---
    def run_collection_series_now(self):
        """Run all loaded collection items one-by-one (series), applying {{vars}} and extractors between requests."""
        # Preconditions
        if not hasattr(self, "_items_data") or not self._items_data:
            messagebox.showwarning("Run Collection", "No collection items loaded.")
            return
        if self._batch_running:
            messagebox.showwarning("Run Collection", "Another batch run is already in progress.")
            return

        items = list(self.ctrl.requests or [])  # current order
        total = len(items)
        if total <= 0:
            messagebox.showwarning("Run Collection", "Collection has no request items to run.")
            return

        # Initialize batch state (reuse your existing progress mechanism)
        self._batch_running = True
        self._batch_cancelled = False
        self._batch_total = total
        self._batch_completed = 0
        self._update_progress_label(f"0/{total}")

        # Optional: disable Compare during batch (avoid pairwise compare interference)
        try:
            self._parallel_prev_compare_state = bool(self.compare_var.get())
            self.compare_var.set(False)
        except Exception:
            self._parallel_prev_compare_state = None

        def _series_runner():
            try:
                for i, it in enumerate(items, start=1):
                    if self._batch_cancelled:
                        break
                    # Extract request parts from item
                    method = (it.get("method") or "GET").upper()
                    url_tmpl = it.get("url") or ""
                    headers = dict(it.get("headers") or {})
                    body_bytes = it.get("body_bytes") or b""

                    # IMPORTANT: Render with collection variables right now (same as Send path)
                    r_url, r_headers, r_body = eng._render_with_vars(self.folder, url_tmpl, headers, body_bytes)

                    # Send using the existing thread-based sender (keeps UI responsive)
                    self._do_request_thread(i - 1, method, url_tmpl, r_headers, r_body)

                    # Progress tick in UI thread
                    self.after(0, self._increment_progress)

                    # Optional small pause to avoid hammering servers; adjust if you like
                    # time.sleep(0.05)
            finally:
                # Restore Compare checkbox state when done
                def _done_ui():
                    if self._parallel_prev_compare_state is not None:
                        try:
                            self.compare_var.set(self._parallel_prev_compare_state)
                        except Exception:
                            pass
                    self._parallel_prev_compare_state = None
                    self._batch_running = False
                self.after(0, _done_ui)

        threading.Thread(target=_series_runner, daemon=True).start()
    # --- END ADD: series runner for entire collection ---

    def _start_batch_run(self, source: str, mode: str, n: int, delay_ms: int, workers: int,
                         csv_path: Optional[Path], dlg: tk.Toplevel):
        if self._batch_running:
            messagebox.showwarning("Run", "A batch run is already in progress.")
            return

        method = self.method_var.get().upper()
        url_current = self.ent_url.get().strip()
        headers_text_current = self.txt_headers.get("1.0", tk.END)
        body_text_current = self.txt_payload.get("1.0", tk.END)
        headers_current = self._parse_headers_from_text(headers_text_current)
        body_current = body_text_current.encode("utf-8") if body_text_current.strip() else b""

        total = 0
        rows_cache: List[Dict[str, str]] = []
        if source == "same":
            total = int(max(0, n))
            if total <= 0:
                messagebox.showerror("Run", "Please enter a positive Count (N).")
                return
        else:
            if not csv_path or not csv_path.exists():
                messagebox.showerror("Run (CSV)", "Please choose a valid CSV file.")
                return
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                rdr = csv.DictReader(f)
                rows_cache = list(rdr)
                total = len(rows_cache)
                if total <= 0:
                    messagebox.showerror("Run (CSV)", "The CSV contains no data rows.")
                    return

        approx_per = max(512, len(headers_text_current) + len(body_text_current) + 1024)
        if total * approx_per > 50 * 1024 * 1024:
            messagebox.showwarning("Log size", "This run may generate a large log (> ~50 MB).")

        self._batch_running = True
        self._batch_cancelled = False
        self._batch_total = total
        self._batch_completed = 0
        self._update_progress_label(f"0/{total}")

        try:
            for child in dlg.winfo_children():
                if isinstance(child, (ttk.Entry, ttk.Button, ttk.Radiobutton, ttk.Combobox, ttk.Checkbutton)):
                    child.configure(state=tk.DISABLED)
        except Exception:
            pass

        def runner():
            try:
                if source == "same":
                    if mode == "series":
                        self._series_runner_same(total, int(delay_ms or 0),
                                                 method, url_current, headers_current, body_current)
                    else:
                        self._parallel_runner_same(total, int(workers or 1),
                                                   method, url_current, headers_current, body_current)
                else:
                    self._series_runner_csv(rows_cache, method,
                                            url_current, headers_text_current, body_text_current,
                                            int(delay_ms or 0))
            finally:
                def _done_ui():
                    try:
                        for child in dlg.winfo_children():
                            if isinstance(child, (ttk.Entry, ttk.Button, ttk.Radiobutton, ttk.Combobox, ttk.Checkbutton)):
                                child.configure(state=tk.NORMAL)
                    except Exception:
                        pass
                    if self._parallel_prev_compare_state is not None:
                        try:
                            self.compare_var.set(self._parallel_prev_compare_state)
                        except Exception:
                            pass
                    self._parallel_prev_compare_state = None
                self.after(0, _done_ui)

        threading.Thread(target=runner, daemon=True).start()

    def open_run_dialog(self):
        win = tk.Toplevel(self)
        win.title("Run requests")
        win.transient(self)
        win.grab_set()

        source_var = tk.StringVar(value="same")
        mode_var = tk.StringVar(value="series")
        n_var = tk.StringVar(value="10")
        delay_var = tk.StringVar(value="0")
        workers_var = tk.StringVar(value="4")
        csv_path_var = tk.StringVar(value="")

        frm = ttk.Frame(win); frm.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)

        ttk.Label(frm, text="Source").grid(row=0, column=0, sticky="w")
        rb_same = ttk.Radiobutton(frm, text="Same Request", variable=source_var, value="same")
        rb_csv = ttk.Radiobutton(frm, text="CSV Data File", variable=source_var, value="csv")
        rb_same.grid(row=0, column=1, sticky="w", padx=6)
        rb_csv.grid(row=0, column=2, sticky="w", padx=6)

        ttk.Label(frm, text="Mode").grid(row=1, column=0, sticky="w")
        rb_series = ttk.Radiobutton(frm, text="Series", variable=mode_var, value="series")
        rb_parallel = ttk.Radiobutton(frm, text="Parallel (Same Request only)", variable=mode_var, value="parallel")
        rb_series.grid(row=1, column=1, sticky="w", padx=6)
        rb_parallel.grid(row=1, column=2, sticky="w", padx=6)

        ttk.Label(frm, text="Count (N)").grid(row=2, column=0, sticky="w")
        ent_n = ttk.Entry(frm, textvariable=n_var, width=12)
        ent_n.grid(row=2, column=1, sticky="w", padx=6)

        ttk.Label(frm, text="Delay (ms, series only)").grid(row=3, column=0, sticky="w")
        ent_delay = ttk.Entry(frm, textvariable=delay_var, width=12)
        ent_delay.grid(row=3, column=1, sticky="w", padx=6)

        ttk.Label(frm, text="Workers (parallel)").grid(row=4, column=0, sticky="w")
        ent_workers = ttk.Entry(frm, textvariable=workers_var, width=12)
        ent_workers.grid(row=4, column=1, sticky="w", padx=6)

        ttk.Label(frm, text="CSV file (UTF‑8, comma, header)").grid(row=5, column=0, sticky="w")
        ent_csv = ttk.Entry(frm, textvariable=csv_path_var, width=50)
        ent_csv.grid(row=5, column=1, columnspan=2, sticky="we", padx=6)
        def choose_csv():
            p = filedialog.askopenfilename(title="Choose CSV", filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
            if p:
                csv_path_var.set(p)
        ttk.Button(frm, text="Browse...", command=choose_csv).grid(row=5, column=3, sticky="w")
        frm.columnconfigure(2, weight=1)

        def refresh_states(*_):
            src = source_var.get()
            mode = mode_var.get()
            csv_selected = (src == "csv")
            if csv_selected:
                mode_var.set("series")
            rb_parallel.state(["disabled"] if csv_selected else ["!disabled"])
            ent_n.state(["!disabled"] if src == "same" else ["disabled"])
            ent_workers.state(["!disabled"] if (src == "same" and mode_var.get() == "parallel") else ["disabled"])
            ent_csv.state(["!disabled"] if csv_selected else ["disabled"])

        source_var.trace_add("write", refresh_states)
        mode_var.trace_add("write", refresh_states)
        refresh_states()

        btns = ttk.Frame(win); btns.pack(fill=tk.X, padx=12, pady=(0,12))
        def on_start():
            src = source_var.get()
            mode = mode_var.get()
            try: n = int(n_var.get() or "0")
            except ValueError: n = 0
            try: delay_ms = int(delay_var.get() or "0")
            except ValueError: delay_ms = 0
            try: workers = int(workers_var.get() or "1")
            except ValueError: workers = 1
            csv_path = Path(csv_path_var.get()) if csv_path_var.get().strip() else None
            self._start_batch_run(src, mode, n, delay_ms, workers, csv_path, win)

        def on_cancel():
            if not self._batch_running:
                win.destroy()
                return
            self._batch_cancelled = True
            if self._parallel_executor is not None:
                try:
                    self._parallel_executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    self._parallel_executor.shutdown(wait=False)
                self._parallel_executor = None

        ttk.Button(btns, text="Start", command=on_start).pack(side=tk.LEFT)
        ttk.Button(btns, text="Cancel", command=on_cancel).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="Close", command=win.destroy).pack(side=tk.RIGHT)

if __name__ == "__main__":
    app = ApiGuiApp()
    app.mainloop()
