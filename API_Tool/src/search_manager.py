"""
search_manager.py
-----------------
Search dialog for finding text in response body or request payload.
Features: highlight all matches, real-time search, match count, Prev/Next navigation.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional


def open_response_search(gui, target_widget=None):
    """Open the search dialog, locked to target_widget if provided."""
    if getattr(gui, "_search_win", None) is not None:
        try:
            gui._search_win.lift()
            gui._search_ent.focus_set()
            return
        except Exception:
            gui._search_win = None

    # Lock the search target for this session
    gui._search_target_widget = target_widget

    win = tk.Toplevel(gui)
    title = "Find (Payload)" if target_widget is gui.txt_payload else "Find (Response)"
    win.title(title)
    win.geometry("520x120")
    gui._search_win = win

    # State for match navigation
    gui._search_matches = []   # list of (start_idx, end_idx) strings
    gui._search_current = -1   # index into _search_matches

    row = ttk.Frame(win)
    row.pack(fill=tk.X, padx=10, pady=10)
    ttk.Label(row, text="Find:").pack(side=tk.LEFT)
    ent = ttk.Entry(row)
    ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
    gui._search_ent = ent

    row2 = ttk.Frame(win)
    row2.pack(fill=tk.X, padx=10, pady=(0, 10))

    # Match count label
    count_label = ttk.Label(row2, text="")
    gui._search_count_label = count_label

    def _get_search_target() -> Optional[tk.Text]:
        """Return the locked target widget for this search session."""
        if gui._search_target_widget is not None:
            return gui._search_target_widget
        return gui._get_active_response_text_widget()

    def clear_all_highlights(txt: tk.Text):
        try:
            txt.tag_remove("search_all", "1.0", tk.END)
            txt.tag_remove("search_current", "1.0", tk.END)
        except Exception:
            pass

    def find_all_matches():
        """Find all occurrences, highlight them all, and update the count."""
        txt = _get_search_target()
        if txt is None:
            gui._search_matches = []
            gui._search_current = -1
            count_label.config(text="")
            return

        clear_all_highlights(txt)
        q = ent.get()
        if not q:
            gui._search_matches = []
            gui._search_current = -1
            count_label.config(text="")
            return

        # Configure tags: all matches get a dim highlight, current gets bright
        txt.tag_config("search_all", background="#e8e4b8")
        txt.tag_config("search_current", background="#fff59d")
        # Ensure current renders on top of all
        txt.tag_raise("search_current", "search_all")

        matches = []
        start_pos = "1.0"
        while True:
            idx = txt.search(q, start_pos, stopindex=tk.END, nocase=True)
            if not idx:
                break
            end_pos = f"{idx}+{len(q)}c"
            matches.append((idx, end_pos))
            txt.tag_add("search_all", idx, end_pos)
            start_pos = end_pos

        gui._search_matches = matches
        if matches:
            gui._search_current = 0
            _highlight_current(txt)
        else:
            gui._search_current = -1
            count_label.config(text="No matches")

    def _highlight_current(txt: tk.Text):
        """Highlight the current match brightly and update the label."""
        txt.tag_remove("search_current", "1.0", tk.END)
        if not gui._search_matches or gui._search_current < 0:
            count_label.config(text="No matches")
            return
        start, end = gui._search_matches[gui._search_current]
        txt.tag_add("search_current", start, end)
        txt.see(start)
        txt.mark_set("insert", end)
        count_label.config(text=f"{gui._search_current + 1} of {len(gui._search_matches)}")

    def find_next():
        txt = _get_search_target()
        if txt is None or not gui._search_matches:
            return
        gui._search_current = (gui._search_current + 1) % len(gui._search_matches)
        _highlight_current(txt)

    def find_prev():
        txt = _get_search_target()
        if txt is None or not gui._search_matches:
            return
        gui._search_current = (gui._search_current - 1) % len(gui._search_matches)
        _highlight_current(txt)

    def on_key_release(_evt=None):
        """Real-time search as user types."""
        find_all_matches()

    ent.bind("<KeyRelease>", on_key_release)
    ent.bind("<Return>", lambda _e: find_next())

    ttk.Button(row2, text="Prev", command=find_prev).pack(side=tk.LEFT)
    ttk.Button(row2, text="Next", command=find_next).pack(side=tk.LEFT, padx=(8, 0))
    count_label.pack(side=tk.LEFT, padx=(12, 0))
    ttk.Button(row2, text="Close", command=lambda: on_close()).pack(side=tk.RIGHT)

    def on_close():
        try:
            txt = _get_search_target()
            if txt is not None:
                clear_all_highlights(txt)
        except Exception:
            pass
        gui._search_matches = []
        gui._search_current = -1
        gui._search_target_widget = None
        gui._search_win = None
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", on_close)
    win.transient(gui)
    win.grab_set()
    ent.focus_set()
