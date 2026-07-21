"""
text_helpers.py
---------------
Utilities for Tkinter Text and Entry widgets:
- Double-click to select content inside quotes (excluding the quotes themselves)
- Undo/Redo for Text widgets (native) and Entry widgets (custom stack)
- Best-effort pretty-print for incomplete/malformed JSON
"""

import json
import tkinter as tk
from tkinter import ttk


# ─── Double-Click Inside Quotes ─────────────────────────────────────────────

def bind_smart_double_click(txt_widget: tk.Text):
    """
    Bind double-click on a Text widget so that if the user clicks inside
    a quoted string, only the content between the quotes is selected
    (excluding the quote characters themselves).
    """
    def _on_double_click(event):
        idx = txt_widget.index(f"@{event.x},{event.y}")
        line, col = map(int, idx.split("."))
        line_text = txt_widget.get(f"{line}.0", f"{line}.end")

        if col >= len(line_text):
            return  # click past end of line, let default handle

        # Find if click is inside a quoted string
        quote_start = None
        quote_end = None
        in_quote = False
        start_col = 0

        for i, ch in enumerate(line_text):
            if ch == '"':
                if not in_quote:
                    in_quote = True
                    start_col = i
                else:
                    # Closing quote found
                    if start_col < col <= i:
                        quote_start = start_col + 1
                        quote_end = i
                        break
                    elif col == start_col:
                        quote_start = start_col + 1
                        quote_end = i
                        break
                    in_quote = False

        if quote_start is not None and quote_end is not None and quote_end > quote_start:
            txt_widget.tag_remove("sel", "1.0", tk.END)
            txt_widget.mark_set("insert", f"{line}.{quote_end}")
            txt_widget.tag_add("sel", f"{line}.{quote_start}", f"{line}.{quote_end}")
            return "break"

        return None

    txt_widget.bind("<Double-Button-1>", _on_double_click)


# ─── Entry Widget Undo/Redo ──────────────────────────────────────────────────

class EntryUndoManager:
    """Provides Ctrl+Z / Ctrl+Y undo/redo for ttk.Entry widgets."""

    def __init__(self, entry_widget):
        self.entry = entry_widget
        self.undo_stack = []
        self.redo_stack = []
        self._last_value = entry_widget.get()

        # Track changes via KeyRelease and FocusIn (catches programmatic changes)
        entry_widget.bind("<KeyRelease>", self._on_change)
        entry_widget.bind("<FocusIn>", self._snapshot)
        entry_widget.bind("<FocusOut>", self._snapshot)
        entry_widget.bind("<Control-z>", self._undo)
        entry_widget.bind("<Control-Z>", self._undo)
        entry_widget.bind("<Control-y>", self._redo)
        entry_widget.bind("<Control-Y>", self._redo)

    def _snapshot(self, event=None):
        """Capture current value if it changed (handles programmatic updates)."""
        current = self.entry.get()
        if current != self._last_value:
            self.undo_stack.append(self._last_value)
            self.redo_stack.clear()
            self._last_value = current

    def _on_change(self, event=None):
        # Ignore the undo/redo key combos themselves
        if event and event.keysym in ("z", "Z", "y", "Y") and (event.state & 0x4):
            return
        current = self.entry.get()
        if current != self._last_value:
            self.undo_stack.append(self._last_value)
            self.redo_stack.clear()
            self._last_value = current

    def _undo(self, event=None):
        # Snapshot current state in case focus didn't catch it
        self._snapshot()
        if self.undo_stack:
            current = self.entry.get()
            self.redo_stack.append(current)
            prev = self.undo_stack.pop()
            self._last_value = prev
            self.entry.delete(0, tk.END)
            self.entry.insert(0, prev)
        return "break"

    def _redo(self, event=None):
        if self.redo_stack:
            current = self.entry.get()
            self.undo_stack.append(current)
            next_val = self.redo_stack.pop()
            self._last_value = next_val
            self.entry.delete(0, tk.END)
            self.entry.insert(0, next_val)
        return "break"


# ─── Incomplete JSON Pretty-Print ────────────────────────────────────────────

def best_effort_pretty_print(raw_text: str) -> str:
    """
    Attempt to pretty-print JSON text even if it has syntax errors.
    If valid, uses json.dumps. Otherwise, applies heuristic indentation
    based on braces/brackets so the user can visually locate the problem.
    """
    # First try normal parse
    try:
        parsed = json.loads(raw_text)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        pass

    # Fallback: heuristic indentation based on { } [ ] structure
    result_lines = []
    indent_level = 0
    indent_str = "  "
    current_line = ""
    in_string = False
    escape_next = False

    for ch in raw_text:
        if escape_next:
            current_line += ch
            escape_next = False
            continue

        if ch == '\\' and in_string:
            current_line += ch
            escape_next = True
            continue

        if ch == '"' and not escape_next:
            in_string = not in_string
            current_line += ch
            continue

        if in_string:
            current_line += ch
            continue

        # Outside of strings - handle structural characters
        if ch in ('{', '['):
            current_line += ch
            result_lines.append(indent_str * indent_level + current_line.strip())
            indent_level += 1
            current_line = ""
        elif ch in ('}', ']'):
            if current_line.strip():
                result_lines.append(indent_str * indent_level + current_line.strip())
                current_line = ""
            indent_level = max(0, indent_level - 1)
            result_lines.append(indent_str * indent_level + ch)
        elif ch == ',':
            current_line += ch
            result_lines.append(indent_str * indent_level + current_line.strip())
            current_line = ""
        elif ch == ':':
            current_line += ": "
        elif ch in (' ', '\t', '\r', '\n'):
            pass  # Skip extra whitespace outside strings
        else:
            current_line += ch

    # Flush remaining
    if current_line.strip():
        result_lines.append(indent_str * indent_level + current_line.strip())

    return "\n".join(result_lines)


def find_error_line_in_pretty(pretty_text: str, error) -> int:
    """
    Given pretty-printed text and a json.JSONDecodeError, estimate which line
    in the pretty-printed version corresponds to the error.
    Returns 1-indexed line number.
    """
    lines = pretty_text.splitlines()
    if not lines:
        return 1

    error_msg = error.msg.lower()

    # For "end of" or "expecting" errors, point to the last non-empty line
    if "end of" in error_msg or "expecting" in error_msg:
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip():
                return i + 1
        return len(lines)

    # Try to map original error position to pretty-printed text
    orig_pos = getattr(error, 'pos', None)
    if orig_pos is not None:
        # Get a snippet around the error position in original doc
        doc = getattr(error, 'doc', '')
        start = max(0, orig_pos - 10)
        end = min(len(doc), orig_pos + 10)
        snippet = doc[start:end].strip()

        # Search for this snippet in pretty-printed text
        if snippet and len(snippet) >= 3:
            for i, line in enumerate(lines):
                if snippet[:5] in line:
                    return i + 1

    # Default: last non-empty line
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip():
            return i + 1
    return len(lines)


def highlight_error_line(txt_widget, line_num: int):
    """Highlight a specific line in a Text widget with a red background."""
    tag_name = "json_error_line"
    txt_widget.tag_remove(tag_name, "1.0", "end")
    txt_widget.tag_config(tag_name, background="#FF3B30", foreground="white")
    txt_widget.tag_add(tag_name, f"{line_num}.0", f"{line_num}.end")
    txt_widget.see(f"{line_num}.0")


# ─── Setup Function ─────────────────────────────────────────────────────────

def setup_text_widgets(gui):
    """
    Apply enhancements to all relevant Text and Entry widgets:
    - Enable undo/redo (Ctrl+Z / Ctrl+Y) for Text widgets (native)
    - Enable undo/redo for Entry widgets (custom stack)
    - Bind smart double-click (select inside quotes)
    """
    # Editable Text widgets get native undo
    editable_widgets = [
        gui.txt_headers,
        gui.txt_payload,
        gui.txt_prerequest,
        gui.txt_tests,
    ]
    for txt in editable_widgets:
        txt.config(undo=True, autoseparators=True, maxundo=-1)

    # Entry widgets get custom undo/redo
    EntryUndoManager(gui.ent_url)
    EntryUndoManager(gui.ent_name)

    # All text widgets with JSON content get smart double-click
    json_widgets = [
        gui.txt_payload,
        gui.txt_resp_body,
        gui.txt_resp_headers,
        gui.txt_headers,
    ]
    for txt in json_widgets:
        bind_smart_double_click(txt)
