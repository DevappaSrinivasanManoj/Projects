"""
curl_handler.py
---------------
cURL paste/parse popup and copy-as-cURL functionality.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict
import threading

import api_engine as eng


def open_curl_popup(gui):
    """Open the paste-cURL popup window."""
    win = tk.Toplevel(gui)
    win.title("Paste cURL")
    win.geometry("900x420")

    txt = tk.Text(win, height=12)
    txt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
    gui.txt_curl = txt

    def _on_close():
        try:
            if getattr(gui, "txt_curl", None) is txt:
                gui.txt_curl = None
        except Exception:
            pass
        win.destroy()

    btns = ttk.Frame(win)
    btns.pack(fill=tk.X, padx=8, pady=(0, 8))
    ttk.Button(btns, text="Parse cURL", command=lambda: parse_curl(gui)).pack(side=tk.LEFT)
    ttk.Button(btns, text="Close", command=_on_close).pack(side=tk.RIGHT)

    win.protocol("WM_DELETE_WINDOW", _on_close)
    win.transient(gui)
    win.grab_set()
    txt.focus_set()


def parse_curl(gui):
    """Parse the cURL command from the popup and populate the request builder."""
    txt = getattr(gui, "txt_curl", None)
    if txt is None:
        messagebox.showwarning("Parse cURL", "Open Paste cURL... first.")
        return
    curl_cmd = txt.get("1.0", tk.END).strip()
    if not curl_cmd:
        messagebox.showwarning("Parse cURL", "Please paste a cURL command.")
        return

    # Run parsing in a thread with a timeout to prevent freezes
    result = [None]
    error = [None]

    def _parse():
        try:
            result[0] = eng.parse_curl(curl_cmd, folder=gui.folder)
        except Exception as e:
            error[0] = str(e)

    t = threading.Thread(target=_parse, daemon=True)
    t.start()
    t.join(timeout=5)  # 5 second timeout

    if t.is_alive():
        messagebox.showerror("Parse cURL", "Could not parse the cURL command (timed out). Please check for unclosed quotes or malformed syntax.")
        _close_curl_popup(gui)
        return

    if error[0]:
        messagebox.showerror("Parse cURL", f"Failed to parse cURL:\n{error[0]}")
        _close_curl_popup(gui)
        return

    method, url, headers, body = result[0]

    # Close the popup on success
    _close_curl_popup(gui)

    gui.method_var.set(method)
    gui.ent_url.delete(0, tk.END)
    gui.ent_url.insert(0, url)
    gui.txt_headers.delete("1.0", tk.END)
    if headers:
        headers_text = "\n".join(f"{k}: {v}" for k, v in headers.items())
        gui.txt_headers.insert(tk.END, headers_text)
    gui._colorize_headers()
    gui.txt_payload.delete("1.0", tk.END)
    if body:
        try:
            gui.txt_payload.insert(tk.END, body.decode("utf-8"))
        except Exception:
            gui.txt_payload.insert(tk.END, "[binary payload]")
    gui._colorize_json(gui.txt_payload)
    messagebox.showinfo("Parse cURL", "Parsed and populated the request builder.")


def _close_curl_popup(gui):
    """Safely closes the cURL paste popup."""
    txt = getattr(gui, "txt_curl", None)
    if txt is not None:
        try:
            win = txt.winfo_toplevel()
            win.grab_release()
            win.destroy()
        except Exception:
            pass
        gui.txt_curl = None


def _shlex_quote_join(parts):
    def shlex_quote(s: str) -> str:
        if not s:
            return "''"
        safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._/:?&=%")
        if all(ch in safe for ch in s):
            return s
        return "'" + s.replace("'", "'\\''") + "'"
    return " ".join(shlex_quote(p) for p in parts)


def copy_as_curl(gui):
    """Build a cURL command from the current request and copy to clipboard."""
    method = gui.method_var.get().upper()
    url = gui.ent_url.get().strip()
    headers = gui._parse_headers_from_text(gui.txt_headers.get("1.0", tk.END))
    body_text = gui.txt_payload.get("1.0", tk.END)
    body = body_text.encode("utf-8") if body_text.strip() else b""

    # Resolve collection variables for curl output
    r_url, r_headers, r_body = eng._render_with_vars(gui.folder, url, headers, body)

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

    curl_str = _shlex_quote_join(parts)
    gui.clipboard_clear()
    gui.clipboard_append(curl_str)
    messagebox.showinfo("Copy as cURL", "cURL command copied to clipboard.")
