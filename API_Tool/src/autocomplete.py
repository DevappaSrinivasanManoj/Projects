"""
autocomplete.py
---------------
Autocomplete popup for {{variable}} placeholders in Text and Entry widgets.
Triggers when the user types '{{', shows dynamic variables and collection variables,
filters as you type, and inserts the selected value with closing '}}'.
"""

import tkinter as tk
from tkinter import ttk
from typing import List, Optional


# Dynamic variables available (same as temp_var_store._DYNAMIC_VARS keys)
DYNAMIC_VARS = [
    "$randomUUID",
    "$guid",
    "$timestamp",
    "$randomInt",
]


class AutocompletePopup:
    """Manages an autocomplete popup for a single Text or Entry widget."""

    def __init__(self, widget, get_collection_vars_fn):
        """
        widget: tk.Text or ttk.Entry to attach to
        get_collection_vars_fn: callable that returns list of collection variable names
        """
        self.widget = widget
        self.get_collection_vars = get_collection_vars_fn
        self.popup: Optional[tk.Toplevel] = None
        self.listbox: Optional[tk.Listbox] = None
        self._active = False
        self._trigger_pos = None  # position where '{{' was typed

        # Bind to key events
        if isinstance(widget, tk.Text):
            widget.bind("<KeyRelease>", self._on_key_release, add="+")
            widget.bind("<FocusOut>", self._hide, add="+")
        else:
            # ttk.Entry
            widget.bind("<KeyRelease>", self._on_key_release_entry, add="+")
            widget.bind("<FocusOut>", self._hide, add="+")

    def _get_all_suggestions(self) -> List[str]:
        """Get all available variable names (dynamic + collection)."""
        suggestions = list(DYNAMIC_VARS)
        try:
            col_vars = self.get_collection_vars()
            suggestions.extend(col_vars)
        except Exception:
            pass
        return suggestions

    def _on_key_release(self, event=None):
        """Handle key release in a Text widget."""
        if event and event.keysym == "Escape":
            self._hide()
            return

        if self._active and event and event.keysym == "Return":
            self._select_current()
            return "break"

        if self._active and event and event.keysym == "Down":
            self._move_selection(1)
            return

        if self._active and event and event.keysym == "Up":
            self._move_selection(-1)
            return

        # Check if we should trigger or update
        cursor_pos = self.widget.index("insert")
        line, col = map(int, cursor_pos.split("."))
        line_text = self.widget.get(f"{line}.0", f"{line}.end")

        # Find the last '{{' before cursor
        text_before = line_text[:col]
        trigger_idx = text_before.rfind("{{")

        if trigger_idx >= 0:
            # Check there's no closing '}}' between trigger and cursor
            between = text_before[trigger_idx + 2:]
            if "}}" not in between:
                # We're inside a {{ ... }} placeholder being typed
                partial = between
                self._trigger_pos = f"{line}.{trigger_idx}"
                self._show_or_update(partial)
                return

        # No trigger found — hide popup if active
        if self._active:
            self._hide()

    def _on_key_release_entry(self, event=None):
        """Handle key release in an Entry widget."""
        if event and event.keysym == "Escape":
            self._hide()
            return

        if self._active and event and event.keysym == "Return":
            self._select_current()
            return "break"

        if self._active and event and event.keysym == "Down":
            self._move_selection(1)
            return

        if self._active and event and event.keysym == "Up":
            self._move_selection(-1)
            return

        # Get text and cursor position
        text = self.widget.get()
        cursor = self.widget.index("insert")
        text_before = text[:cursor]

        trigger_idx = text_before.rfind("{{")
        if trigger_idx >= 0:
            between = text_before[trigger_idx + 2:]
            if "}}" not in between:
                partial = between
                self._trigger_pos = trigger_idx
                self._show_or_update(partial)
                return

        if self._active:
            self._hide()

    def _show_or_update(self, partial: str):
        """Show the popup or update its contents based on partial text."""
        suggestions = self._get_all_suggestions()

        # Filter by partial match
        if partial:
            lower_partial = partial.lower()
            filtered = [s for s in suggestions if lower_partial in s.lower()]
        else:
            filtered = suggestions

        if not filtered:
            self._hide()
            return

        if not self._active:
            self._create_popup()

        # Update listbox
        self.listbox.delete(0, tk.END)
        for item in filtered:
            self.listbox.insert(tk.END, item)

        # Select first item
        if filtered:
            self.listbox.selection_set(0)

        self._active = True

    def _create_popup(self):
        """Create the popup window near the cursor."""
        if self.popup:
            try:
                self.popup.destroy()
            except Exception:
                pass

        self.popup = tk.Toplevel(self.widget)
        self.popup.wm_overrideredirect(True)  # No window decorations
        self.popup.wm_attributes("-topmost", True)

        self.listbox = tk.Listbox(
            self.popup, height=6, width=30,
            font=("Consolas", 9),
            selectmode=tk.SINGLE,
            activestyle="dotbox"
        )
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.listbox.bind("<Double-Button-1>", lambda e: self._select_current())
        self.listbox.bind("<Return>", lambda e: self._select_current())

        # Position popup near cursor
        self._position_popup()

    def _position_popup(self):
        """Position the popup near the text cursor."""
        try:
            if isinstance(self.widget, tk.Text):
                bbox = self.widget.bbox("insert")
                if bbox:
                    x, y, _, h = bbox
                    root_x = self.widget.winfo_rootx() + x
                    root_y = self.widget.winfo_rooty() + y + h + 2
                else:
                    root_x = self.widget.winfo_rootx()
                    root_y = self.widget.winfo_rooty() + self.widget.winfo_height()
            else:
                # Entry widget
                root_x = self.widget.winfo_rootx()
                root_y = self.widget.winfo_rooty() + self.widget.winfo_height() + 2

            self.popup.geometry(f"+{root_x}+{root_y}")
        except Exception:
            pass

    def _select_current(self):
        """Insert the selected suggestion into the widget."""
        if not self.listbox:
            return
        sel = self.listbox.curselection()
        if not sel:
            return
        chosen = self.listbox.get(sel[0])

        if isinstance(self.widget, tk.Text):
            # Delete the partial text (everything after '{{') and insert chosen + '}}'
            cursor_pos = self.widget.index("insert")
            line, col = map(int, cursor_pos.split("."))
            # Delete from after '{{' to cursor
            trigger_line, trigger_col = map(int, self._trigger_pos.split("."))
            delete_start = f"{trigger_line}.{trigger_col + 2}"  # after '{{'
            self.widget.delete(delete_start, "insert")
            self.widget.insert("insert", f"{chosen}}}}}")
        else:
            # Entry widget
            text = self.widget.get()
            cursor = self.widget.index("insert")
            # Replace from trigger+2 to cursor with chosen + '}}'
            before = text[:self._trigger_pos + 2]
            after = text[cursor:]
            new_text = before + chosen + "}}" + after
            self.widget.delete(0, tk.END)
            self.widget.insert(0, new_text)
            # Move cursor after the inserted '}}' 
            new_cursor = len(before) + len(chosen) + 2
            self.widget.icursor(new_cursor)

        self._hide()

    def _move_selection(self, direction: int):
        """Move listbox selection up or down."""
        if not self.listbox:
            return
        sel = self.listbox.curselection()
        if not sel:
            self.listbox.selection_set(0)
            return
        new_idx = sel[0] + direction
        if 0 <= new_idx < self.listbox.size():
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(new_idx)
            self.listbox.see(new_idx)

    def _hide(self, event=None):
        """Hide and destroy the popup."""
        self._active = False
        if self.popup:
            try:
                self.popup.destroy()
            except Exception:
                pass
            self.popup = None
            self.listbox = None


def setup_autocomplete(gui):
    """
    Attach autocomplete to all relevant widgets in the GUI.
    """
    def get_vars():
        """Get current collection variable names."""
        try:
            gui.vars.load()
            return list(gui.vars.data.keys())
        except Exception:
            return []

    # Attach to Text widgets where {{var}} is used
    text_widgets = [
        gui.txt_headers,
        gui.txt_payload,
        gui.txt_prerequest,
        gui.txt_tests,
    ]
    for txt in text_widgets:
        AutocompletePopup(txt, get_vars)

    # Attach to Entry widgets
    AutocompletePopup(gui.ent_url, get_vars)
