import tkinter as tk
from tkinter import ttk

class CollectionEditor:
    @staticmethod
    def inject_controls(gui, parent_frame):
        """Creates the management buttons in the GUI."""
        btn_row = ttk.Frame(parent_frame)
        btn_row.pack(fill=tk.X, padx=4, pady=2)
        
        ttk.Button(btn_row, text="↑", width=3, 
                   command=lambda: CollectionEditor.move_item(gui, -1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="↓", width=3, 
                   command=lambda: CollectionEditor.move_item(gui, 1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Delete", 
                   command=lambda: CollectionEditor.delete_item(gui)).pack(side=tk.LEFT, padx=2)

    @staticmethod
    def move_item(gui, direction):
        sel = gui.lst_items.curselection()
        if not sel: return
        idx = sel[0]
        new_idx = idx + direction
        if 0 <= new_idx < len(gui.ctrl.requests):
            gui.ctrl.requests[idx], gui.ctrl.requests[new_idx] = \
                gui.ctrl.requests[new_idx], gui.ctrl.requests[idx]
            text = gui.lst_items.get(idx)
            gui.lst_items.delete(idx)
            gui.lst_items.insert(new_idx, text)
            gui.lst_items.selection_set(new_idx)
            gui.ctrl.last_index = new_idx

    @staticmethod
    def delete_item(gui):
        sel = gui.lst_items.curselection()
        if not sel: return
        idx = sel[0]
        gui.ctrl.requests.pop(idx)
        gui.lst_items.delete(idx)
        gui.ctrl.last_index = None