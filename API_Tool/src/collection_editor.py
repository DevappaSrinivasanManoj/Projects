import tkinter as tk
from tkinter import ttk

class CollectionEditor:
    @staticmethod
    def inject_controls(gui, parent_frame):
        """Creates the management buttons in the GUI."""
        # Expand/Collapse All row — at the top
        expand_row = ttk.Frame(parent_frame)
        expand_row.pack(fill=tk.X, padx=4, pady=(2, 0))
        ttk.Button(expand_row, text="Expand All",
                   command=lambda: gui._tree_sidebar.expand_all()).pack(side=tk.LEFT, padx=2)
        ttk.Button(expand_row, text="Collapse All",
                   command=lambda: gui._tree_sidebar.collapse_all()).pack(side=tk.LEFT, padx=2)

        # Clear button row
        clear_row = ttk.Frame(parent_frame)
        clear_row.pack(fill=tk.X, padx=4, pady=(2, 0))
        ttk.Button(clear_row, text="Clear All",
                   command=lambda: gui.clear_collection()).pack(side=tk.LEFT, padx=2)
        ttk.Button(clear_row, text="+ New",
                   command=lambda: gui.new_request()).pack(side=tk.LEFT, padx=2)

        btn_row = ttk.Frame(parent_frame)
        btn_row.pack(fill=tk.X, padx=4, pady=2)
        
        ttk.Button(btn_row, text="↑", width=3, 
                   command=lambda: CollectionEditor.move_item(gui, -1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="↓", width=3, 
                   command=lambda: CollectionEditor.move_item(gui, 1)).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="Delete", 
                   command=lambda: CollectionEditor.delete_item(gui)).pack(side=tk.LEFT, padx=2)

    @staticmethod
    def new_folder(gui):
        """Create a new folder in the sidebar."""
        parent_iid = gui._tree_sidebar.get_selected_folder()
        gui._tree_sidebar._create_folder(parent_iid)

    @staticmethod
    def move_item(gui, direction):
        tree = gui._tree_sidebar.tree
        sel = tree.selection()
        if not sel:
            return
        iid = sel[0]
        parent = tree.parent(iid)
        siblings = list(tree.get_children(parent))
        idx = siblings.index(iid)
        new_idx = idx + direction
        if 0 <= new_idx < len(siblings):
            tree.move(iid, parent, new_idx)
            # Also reorder in ctrl.requests if both are requests
            old_data_idx = gui._tree_sidebar._iid_to_index.get(iid)
            swap_iid = siblings[new_idx]
            new_data_idx = gui._tree_sidebar._iid_to_index.get(swap_iid)
            if old_data_idx is not None and new_data_idx is not None:
                gui.ctrl.requests[old_data_idx], gui.ctrl.requests[new_data_idx] = \
                    gui.ctrl.requests[new_data_idx], gui.ctrl.requests[old_data_idx]
                gui._tree_sidebar._rebuild_index_maps()

    @staticmethod
    def delete_item(gui):
        tree = gui._tree_sidebar.tree
        sel = tree.selection()
        if not sel:
            return
        iid = sel[0]
        if gui._tree_sidebar.is_folder(iid):
            gui._tree_sidebar._delete_folder(iid)
        else:
            gui._tree_sidebar._delete_request(iid)
