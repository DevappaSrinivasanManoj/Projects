"""
batch_runner.py
---------------
Batch/collection run logic: Run All, Run N Times, series/parallel/CSV runners,
and the generic Run Dialog.
"""

import re
import csv
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor

import api_engine as eng


_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")


def _extract_placeholders(gui, *texts: str) -> set:
    keys = set()
    for t in texts:
        if not t:
            continue
        tmp = t.replace("{{{{", "\uE000").replace("}}}}", "\uE001")
        for m in _PLACEHOLDER_RE.finditer(tmp):
            keys.add(m.group(1))
    return keys


def _render_template(gui, text: str, ctx: dict) -> str:
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

    s = _PLACEHOLDER_RE.sub(repl, s)
    return s.replace("\uE000", "{").replace("\uE001", "}")


def _reset_progress(gui):
    gui._batch_running = False
    gui._batch_cancelled = False
    gui._batch_total = 0
    gui._batch_completed = 0
    gui._parallel_executor = None
    gui._parallel_prev_compare_state = None
    _update_progress_label(gui, "")


def _update_progress_label(gui, text: str):
    try:
        gui.lbl_progress.config(text=text)
    except Exception:
        pass


def _increment_progress(gui):
    gui._batch_completed += 1
    _update_progress_label(gui, f"{gui._batch_completed}/{gui._batch_total}")
    if gui._batch_completed >= gui._batch_total:
        if gui._parallel_prev_compare_state is not None:
            try:
                gui.compare_var.set(gui._parallel_prev_compare_state)
            except Exception:
                pass
        gui._parallel_prev_compare_state = None
        gui._batch_running = False


def _series_runner_same(gui, n: int, delay_ms: int, method: str, url: str, headers: dict, body: bytes):
    selection = gui.lst_items.curselection()
    req_index = gui.ctrl.last_index if gui.ctrl.last_index is not None else (selection[0] if selection else 0)
    for i in range(n):
        if gui._batch_cancelled:
            break
        gui._do_request_thread(req_index, method, url, dict(headers), body)
        gui.after(0, lambda: _increment_progress(gui))
        if i < n - 1 and delay_ms > 0:
            time.sleep(max(0, delay_ms) / 1000.0)


def _parallel_runner_same(gui, n: int, workers: int, method: str, url: str, headers: dict, body: bytes):
    selection = gui.lst_items.curselection()
    req_index = gui.ctrl.last_index if gui.ctrl.last_index is not None else (selection[0] if selection else 0)
    gui._parallel_prev_compare_state = bool(gui.compare_var.get())
    try:
        gui.compare_var.set(False)
    except Exception:
        pass
    workers = max(1, int(workers or 1))
    gui._parallel_executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="apigui-par")
    futures = []
    try:
        for _ in range(n):
            if gui._batch_cancelled:
                break
            fut = gui._parallel_executor.submit(gui._do_request_thread, req_index, method, url, dict(headers), body)
            futures.append(fut)
            fut.add_done_callback(lambda _f: gui.after(0, lambda: _increment_progress(gui)))
    finally:
        if gui._batch_cancelled:
            try:
                gui._parallel_executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                gui._parallel_executor.shutdown(wait=False)
            gui._parallel_executor = None
        else:
            gui._parallel_executor.shutdown(wait=True)
            gui._parallel_executor = None


def _series_runner_csv(gui, rows: List[Dict[str, str]], method: str,
                       url_tmpl: str, headers_tmpl: str, body_tmpl: str, delay_ms: int):
    selection = gui.lst_items.curselection()
    req_index = gui.ctrl.last_index if gui.ctrl.last_index is not None else (selection[0] if selection else 0)
    header = list(rows[0].keys()) if rows else []
    for i, row in enumerate(rows, start=1):
        if gui._batch_cancelled:
            break
        ctx = {k: ("" if row.get(k) is None else str(row.get(k))) for k in header}
        url = _render_template(gui, url_tmpl, ctx).strip()
        hdrs_text = _render_template(gui, headers_tmpl, ctx)
        body_text = _render_template(gui, body_tmpl, ctx)
        headers = gui._parse_headers_from_text(hdrs_text)
        body = body_text.encode("utf-8") if body_text.strip() else b""
        url, headers, body = eng._render_with_vars(gui.folder, url, headers, body)
        gui._do_request_thread(req_index, method, url, headers, body)
        gui.after(0, lambda: _increment_progress(gui))
        if i < gui._batch_total and delay_ms > 0:
            time.sleep(max(0, delay_ms) / 1000.0)


def open_run_collection_n_dialog(gui):
    """Dialog for entering N and delay for running collection N times."""
    if not hasattr(gui, "_items_data") or not gui._items_data:
        messagebox.showwarning("Run N Times", "No collection loaded.")
        return

    win = tk.Toplevel(gui)
    win.title("Run Collection N Times")
    win.transient(gui); win.grab_set()

    ttk.Label(win, text="How many times?").pack(padx=10, pady=(10, 5))
    n_var = tk.StringVar(value="1")
    ent_n = ttk.Entry(win, textvariable=n_var, width=10)
    ent_n.pack(padx=10, pady=5)

    ttk.Label(win, text="Delay between requests (ms):").pack(padx=10, pady=(10, 5))
    delay_var = tk.StringVar(value="0")
    ent_delay = ttk.Entry(win, textvariable=delay_var, width=10)
    ent_delay.pack(padx=10, pady=5)

    def on_start():
        try:
            n = int(n_var.get())
            if n <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Run N Times", "Enter a valid positive number.")
            return
        try:
            delay_ms = int(delay_var.get())
            if delay_ms < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Run N Times", "Enter a valid non-negative delay (ms).")
            return
        win.destroy()
        run_collection_n_times(gui, n, delay_ms)

    ttk.Button(win, text="Start", command=on_start).pack(padx=10, pady=10)


def run_collection_n_times(gui, n: int, delay_ms: int = 0):
    """Runs the entire collection N times."""
    if not hasattr(gui, "_items_data") or not gui._items_data:
        messagebox.showwarning("Run Collection", "No collection loaded.")
        return

    total_items = len(gui._items_data)
    total_runs = total_items * n

    if gui._batch_running:
        messagebox.showwarning("Run Collection", "Another batch is already active.")
        return

    gui._batch_running = True
    gui._batch_cancelled = False
    gui._batch_total = total_runs
    gui._batch_completed = 0
    _update_progress_label(gui, f"0/{total_runs}")

    try:
        gui._parallel_prev_compare_state = bool(gui.compare_var.get())
        gui.compare_var.set(False)
    except Exception:
        gui._parallel_prev_compare_state = None

    items = list(gui.ctrl.requests or [])
    delay_sec = delay_ms / 1000.0

    def _runner():
        try:
            request_counter = 0
            for _ in range(n):
                if gui._batch_cancelled:
                    break
                for req_index, it in enumerate(items):
                    if gui._batch_cancelled:
                        break
                    method = (it.get("method") or "GET").upper()
                    tmpl_url = it.get("url") or ""
                    headers = dict(it.get("headers") or {})
                    body = it.get("body_bytes") or b""

                    r_url, r_headers, r_body = eng._render_with_vars(gui.folder, tmpl_url, headers, body)
                    gui._do_request_thread(req_index, method, tmpl_url, r_headers, r_body)

                    gui.after(0, lambda: _increment_progress(gui))
                    request_counter += 1

                    if delay_sec > 0 and request_counter < total_runs:
                        time.sleep(delay_sec)
        finally:
            def _done_ui():
                if gui._parallel_prev_compare_state is not None:
                    try:
                        gui.compare_var.set(gui._parallel_prev_compare_state)
                    except Exception:
                        pass
                gui._parallel_prev_compare_state = None
                gui._batch_running = False
            gui.after(0, _done_ui)

    threading.Thread(target=_runner, daemon=True).start()


def open_run_collection_delay_dialog(gui):
    """Prompt for delay (ms) before running the full collection in series."""
    if not hasattr(gui, "_items_data") or not gui._items_data:
        messagebox.showwarning("Run Collection", "No collection loaded.")
        return
    if gui._batch_running:
        messagebox.showwarning("Run Collection", "Another batch run is already in progress.")
        return

    win = tk.Toplevel(gui)
    win.title("Run Collection (All)")
    win.transient(gui); win.grab_set()

    ttk.Label(win, text="Delay between requests (ms):").pack(padx=10, pady=(10, 5))
    delay_var = tk.StringVar(value="0")
    ent = ttk.Entry(win, textvariable=delay_var, width=10)
    ent.pack(padx=10, pady=5)

    def on_start():
        try:
            delay_ms = int(delay_var.get())
            if delay_ms < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Run Collection", "Enter a valid non-negative number (ms).")
            return
        win.destroy()
        run_collection_series_now(gui, delay_ms)

    ttk.Button(win, text="Start", command=on_start).pack(padx=10, pady=10)


def run_collection_series_now(gui, delay_ms: int = 0):
    """Run all loaded collection items one-by-one (series)."""
    if not hasattr(gui, "_items_data") or not gui._items_data:
        messagebox.showwarning("Run Collection", "No collection items loaded.")
        return
    if gui._batch_running:
        messagebox.showwarning("Run Collection", "Another batch run is already in progress.")
        return

    items = list(gui.ctrl.requests or [])
    total = len(items)
    if total <= 0:
        messagebox.showwarning("Run Collection", "Collection has no request items to run.")
        return

    gui._batch_running = True
    gui._batch_cancelled = False
    gui._batch_total = total
    gui._batch_completed = 0
    _update_progress_label(gui, f"0/{total}")

    try:
        gui._parallel_prev_compare_state = bool(gui.compare_var.get())
        gui.compare_var.set(False)
    except Exception:
        gui._parallel_prev_compare_state = None

    delay_sec = delay_ms / 1000.0

    def _series_runner():
        try:
            for i, it in enumerate(items, start=1):
                if gui._batch_cancelled:
                    break
                method = (it.get("method") or "GET").upper()
                url_tmpl = it.get("url") or ""
                headers = dict(it.get("headers") or {})
                body_bytes = it.get("body_bytes") or b""

                r_url, r_headers, r_body = eng._render_with_vars(gui.folder, url_tmpl, headers, body_bytes)
                gui._do_request_thread(i - 1, method, url_tmpl, r_headers, r_body)

                gui.after(0, lambda: _increment_progress(gui))

                if delay_sec > 0 and i < total:
                    time.sleep(delay_sec)
        finally:
            def _done_ui():
                if gui._parallel_prev_compare_state is not None:
                    try:
                        gui.compare_var.set(gui._parallel_prev_compare_state)
                    except Exception:
                        pass
                gui._parallel_prev_compare_state = None
                gui._batch_running = False
            gui.after(0, _done_ui)

    threading.Thread(target=_series_runner, daemon=True).start()


def _start_batch_run(gui, source: str, mode: str, n: int, delay_ms: int, workers: int,
                     csv_path: Optional[Path], dlg: tk.Toplevel):
    if gui._batch_running:
        messagebox.showwarning("Run", "A batch run is already in progress.")
        return

    method = gui.method_var.get().upper()
    url_current = gui.ent_url.get().strip()
    headers_text_current = gui.txt_headers.get("1.0", tk.END)
    body_text_current = gui.txt_payload.get("1.0", tk.END)
    headers_current = gui._parse_headers_from_text(headers_text_current)
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

    gui._batch_running = True
    gui._batch_cancelled = False
    gui._batch_total = total
    gui._batch_completed = 0
    _update_progress_label(gui, f"0/{total}")

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
                    _series_runner_same(gui, total, int(delay_ms or 0),
                                        method, url_current, headers_current, body_current)
                else:
                    _parallel_runner_same(gui, total, int(workers or 1),
                                          method, url_current, headers_current, body_current)
            else:
                _series_runner_csv(gui, rows_cache, method,
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
                if gui._parallel_prev_compare_state is not None:
                    try:
                        gui.compare_var.set(gui._parallel_prev_compare_state)
                    except Exception:
                        pass
                gui._parallel_prev_compare_state = None
            gui.after(0, _done_ui)

    threading.Thread(target=runner, daemon=True).start()


def open_run_dialog(gui):
    """Open the generic batch run dialog (Same Request or CSV)."""
    win = tk.Toplevel(gui)
    win.title("Run requests")
    win.transient(gui)
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

    ttk.Label(frm, text="CSV file (UTF-8, comma, header)").grid(row=5, column=0, sticky="w")
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

    btns = ttk.Frame(win); btns.pack(fill=tk.X, padx=12, pady=(0, 12))

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
        _start_batch_run(gui, src, mode, n, delay_ms, workers, csv_path, win)

    def on_cancel():
        if not gui._batch_running:
            win.destroy()
            return
        gui._batch_cancelled = True
        if gui._parallel_executor is not None:
            try:
                gui._parallel_executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                gui._parallel_executor.shutdown(wait=False)
            gui._parallel_executor = None

    ttk.Button(btns, text="Start", command=on_start).pack(side=tk.LEFT)
    ttk.Button(btns, text="Cancel", command=on_cancel).pack(side=tk.LEFT, padx=6)
    ttk.Button(btns, text="Close", command=win.destroy).pack(side=tk.RIGHT)



def open_selective_run_dialog(gui):
    """
    Open a dialog showing all requests in the collection with checkboxes.
    User can select which ones to run, set a delay, and start.
    """
    if not hasattr(gui, "_items_data") or not gui._items_data:
        messagebox.showwarning("Run Selected", "No collection loaded.")
        return
    if gui._batch_running:
        messagebox.showwarning("Run Selected", "Another batch run is already in progress.")
        return

    items = list(gui.ctrl.requests or [])
    if not items:
        messagebox.showwarning("Run Selected", "No requests in collection.")
        return

    win = tk.Toplevel(gui)
    win.title("Run Selected Requests")
    win.geometry("600x500")
    win.transient(gui)
    win.grab_set()

    ttk.Label(win, text="Select requests to run:").pack(anchor="w", padx=10, pady=(10, 5))

    # Scrollable frame with checkboxes
    canvas_frame = ttk.Frame(win)
    canvas_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

    canvas = tk.Canvas(canvas_frame)
    scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
    scrollable = ttk.Frame(canvas)

    scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=scrollable, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    # Create checkboxes for each request
    check_vars = []
    for i, it in enumerate(items):
        name = it.get("name", "")
        method = it.get("method", "GET")
        url = it.get("url", "")
        display = name if name.strip() else f"{method} {url}"

        var = tk.BooleanVar(value=True)
        check_vars.append(var)
        ttk.Checkbutton(scrollable, text=f"{i+1}. {display}", variable=var).pack(anchor="w", padx=5, pady=1)

    # Select All / Deselect All buttons
    btn_frame = ttk.Frame(win)
    btn_frame.pack(fill=tk.X, padx=10, pady=(5, 0))
    ttk.Button(btn_frame, text="Select All", command=lambda: [v.set(True) for v in check_vars]).pack(side=tk.LEFT, padx=2)
    ttk.Button(btn_frame, text="Deselect All", command=lambda: [v.set(False) for v in check_vars]).pack(side=tk.LEFT, padx=2)

    # Delay input
    delay_frame = ttk.Frame(win)
    delay_frame.pack(fill=tk.X, padx=10, pady=(10, 5))
    ttk.Label(delay_frame, text="Delay between requests (ms):").pack(side=tk.LEFT)
    delay_var = tk.StringVar(value="0")
    ttk.Entry(delay_frame, textvariable=delay_var, width=10).pack(side=tk.LEFT, padx=(8, 0))

    # Start / Close buttons
    action_frame = ttk.Frame(win)
    action_frame.pack(fill=tk.X, padx=10, pady=10)

    def on_start():
        selected_indices = [i for i, v in enumerate(check_vars) if v.get()]
        if not selected_indices:
            messagebox.showwarning("Run Selected", "No requests selected.")
            return
        try:
            delay_ms = int(delay_var.get())
            if delay_ms < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Run Selected", "Enter a valid non-negative delay (ms).")
            return
        win.destroy()
        _run_selected_requests(gui, selected_indices, delay_ms)

    ttk.Button(action_frame, text="Run Selected", command=on_start).pack(side=tk.LEFT)
    ttk.Button(action_frame, text="Close", command=win.destroy).pack(side=tk.RIGHT)


def _run_selected_requests(gui, indices: List[int], delay_ms: int = 0):
    """Run only the selected requests in series with optional delay."""
    items = gui.ctrl.requests
    total = len(indices)

    gui._batch_running = True
    gui._batch_cancelled = False
    gui._batch_total = total
    gui._batch_completed = 0
    _update_progress_label(gui, f"0/{total}")

    try:
        gui._parallel_prev_compare_state = bool(gui.compare_var.get())
        gui.compare_var.set(False)
    except Exception:
        gui._parallel_prev_compare_state = None

    delay_sec = delay_ms / 1000.0

    def _runner():
        try:
            for count, idx in enumerate(indices, start=1):
                if gui._batch_cancelled:
                    break
                if idx >= len(items):
                    continue
                it = items[idx]
                method = (it.get("method") or "GET").upper()
                url_tmpl = it.get("url") or ""
                headers = dict(it.get("headers") or {})
                body = it.get("body_bytes") or b""

                r_url, r_headers, r_body = eng._render_with_vars(gui.folder, url_tmpl, headers, body)
                gui._do_request_thread(idx, method, url_tmpl, r_headers, r_body)

                gui.after(0, lambda: _increment_progress(gui))

                if delay_sec > 0 and count < total:
                    time.sleep(delay_sec)
        finally:
            def _done_ui():
                if gui._parallel_prev_compare_state is not None:
                    try:
                        gui.compare_var.set(gui._parallel_prev_compare_state)
                    except Exception:
                        pass
                gui._parallel_prev_compare_state = None
                gui._batch_running = False
            gui.after(0, _done_ui)

    threading.Thread(target=_runner, daemon=True).start()
