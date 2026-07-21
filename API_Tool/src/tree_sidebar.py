"""
tree_sidebar.py
---------------
Treeview-based sidebar with folder support for the API tool.
Replaces the flat Listbox with a hierarchical tree that supports:
- Folders (expand/collapse)
- Requests nested under folders
- Compatible API surface with the old Listbox usage
"""

import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from typing import Optional, List, Dict, Any


class TreeSidebar:
    """
    Wraps a ttk.Treeview to provide folder + request hierarchy.
    Each item in the tree stores:
      - For folders: tag="folder", no data index
      - For requests: tag="request", maps to an index in ctrl.requests
    """

    def __init__(self, parent_frame, gui):
        self.gui = gui
        self.tree = ttk.Treeview(parent_frame, show="tree", selectmode="browse")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Bind selection
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Button-3>", self._on_right_click)

        # Store mapping: tree item iid -> index in ctrl.requests (for requests only)
        # Folders have no index mapping
        self._iid_to_index: Dict[str, int] = {}
        self._index_to_iid: Dict[int, str] = {}

    # ─── Compatibility Layer (mimics old Listbox API) ────────────────────

    def curselection(self):
        """Returns a tuple with the selected request index, or empty tuple."""
        sel = self.tree.selection()
        if not sel:
            return ()
        iid = sel[0]
        if iid in self._iid_to_index:
            return (self._iid_to_index[iid],)
        return ()

    def selection_clear(self, *args):
        """Clear all selections."""
        for item in self.tree.selection():
            self.tree.selection_remove(item)

    def selection_set(self, index):
        """Select the request at the given index."""
        if index in self._index_to_iid:
            iid = self._index_to_iid[index]
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def delete(self, *args):
        """Delete all items (when called with 0, END) or a specific index."""
        if len(args) == 2 and args[0] == 0:
            # delete(0, END) — clear all
            for item in self.tree.get_children(""):
                self.tree.delete(item)
            self._iid_to_index.clear()
            self._index_to_iid.clear()
        elif len(args) == 1 and isinstance(args[0], int):
            # delete a specific request by index
            idx = args[0]
            if idx in self._index_to_iid:
                iid = self._index_to_iid[idx]
                self.tree.delete(iid)
                del self._iid_to_index[iid]
                del self._index_to_iid[idx]
                # Re-index everything above this
                self._rebuild_index_maps()

    def insert(self, position, text, parent_iid="", tags=("request",)):
        """Insert a request item. Returns the iid."""
        if position == tk.END:
            iid = self.tree.insert(parent_iid, "end", text=text, tags=tags)
        else:
            iid = self.tree.insert(parent_iid, position, text=text, tags=tags)
        return iid

    def get(self, index):
        """Get display text for a request at index."""
        if index in self._index_to_iid:
            iid = self._index_to_iid[index]
            return self.tree.item(iid, "text")
        return ""

    # ─── Folder Operations ───────────────────────────────────────────────

    def add_folder(self, name: str, parent_iid: str = "") -> str:
        """Add a folder node to the tree. Returns the folder's iid."""
        iid = self.tree.insert(parent_iid, "end", text=f"📁 {name}", tags=("folder",), open=False)
        return iid

    def get_selected_folder(self) -> str:
        """Get the iid of the folder context for the current selection.
        If a request is selected, returns its parent. If a folder, returns itself.
        If nothing, returns root ('')."""
        sel = self.tree.selection()
        if not sel:
            return ""
        iid = sel[0]
        if "folder" in self.tree.item(iid, "tags"):
            return iid
        # It's a request, return its parent
        return self.tree.parent(iid)

    def is_folder(self, iid: str) -> bool:
        """Check if an iid is a folder."""
        return "folder" in self.tree.item(iid, "tags")

    def expand_all(self):
        """Expand all folder nodes in the tree."""
        self._set_open_recursive("", True)

    def collapse_all(self):
        """Collapse all folder nodes in the tree."""
        self._set_open_recursive("", False)

    def _set_open_recursive(self, parent: str, is_open: bool):
        for iid in self.tree.get_children(parent):
            if "folder" in self.tree.item(iid, "tags"):
                self.tree.item(iid, open=is_open)
                self._set_open_recursive(iid, is_open)

    # ─── Population ──────────────────────────────────────────────────────

    def populate_flat(self, items: List[Dict[str, Any]]):
        """Populate the tree with a flat list of requests (no folders)."""
        self.delete(0, tk.END)
        for i, it in enumerate(items):
            name = it.get("name", "")
            method = it.get("method", "GET")
            url = it.get("url", "")
            display = name if name.strip() else f"{method} {url}"
            iid = self.tree.insert("", "end", text=display, tags=("request",))
            self._iid_to_index[iid] = i
            self._index_to_iid[i] = iid

    def populate_with_folders(self, items: List[Dict[str, Any]]):
        """
        Populate the tree preserving folder structure.
        Items with a 'path' like 'FolderA/FolderB/RequestName' get nested.
        Items without a path go to root.
        """
        self.delete(0, tk.END)
        folder_cache: Dict[str, str] = {}  # folder_path -> iid

        for i, it in enumerate(items):
            path = it.get("path", "")
            name = it.get("name", "")
            method = it.get("method", "GET")
            url = it.get("url", "")
            display = name if name.strip() else f"{method} {url}"

            # Determine parent folder
            if "/" in path:
                # path is like "FolderA/FolderB/RequestName"
                parts = path.split("/")
                folder_parts = parts[:-1]  # everything except the request name
                parent_iid = self._ensure_folder_path(folder_parts, folder_cache)
            else:
                parent_iid = ""

            iid = self.tree.insert(parent_iid, "end", text=display, tags=("request",))
            self._iid_to_index[iid] = i
            self._index_to_iid[i] = iid

    def _ensure_folder_path(self, parts: List[str], cache: Dict[str, str]) -> str:
        """Ensure all folders in the path exist, creating as needed. Returns leaf folder iid."""
        current_path = ""
        parent_iid = ""
        for part in parts:
            current_path = f"{current_path}/{part}" if current_path else part
            if current_path not in cache:
                iid = self.tree.insert(parent_iid, "end", text=f"📁 {part}", tags=("folder",), open=False)
                cache[current_path] = iid
            parent_iid = cache[current_path]
        return parent_iid

    # ─── Request Index Management ────────────────────────────────────────

    def add_request(self, index: int, display_text: str, parent_iid: str = "") -> str:
        """Add a request to the tree at a specific data index."""
        iid = self.tree.insert(parent_iid, "end", text=display_text, tags=("request",))
        self._iid_to_index[iid] = index
        self._index_to_iid[index] = iid
        return iid

    def remove_request(self, index: int):
        """Remove a request by its data index."""
        if index in self._index_to_iid:
            iid = self._index_to_iid[index]
            self.tree.delete(iid)
            del self._iid_to_index[iid]
            del self._index_to_iid[index]
            self._rebuild_index_maps()

    def update_request_text(self, index: int, text: str):
        """Update the display text for a request at index."""
        if index in self._index_to_iid:
            iid = self._index_to_iid[index]
            self.tree.item(iid, text=text)

    def _rebuild_index_maps(self):
        """Rebuild index maps by walking the tree in order."""
        self._iid_to_index.clear()
        self._index_to_iid.clear()
        idx = 0
        self._walk_tree("", idx_counter=[0])

    def _walk_tree(self, parent: str, idx_counter: list):
        """Recursively walk tree and assign indices to requests."""
        for iid in self.tree.get_children(parent):
            if "request" in self.tree.item(iid, "tags"):
                self._iid_to_index[iid] = idx_counter[0]
                self._index_to_iid[idx_counter[0]] = iid
                idx_counter[0] += 1
            elif "folder" in self.tree.item(iid, "tags"):
                self._walk_tree(iid, idx_counter)

    def get_all_request_indices_in_order(self) -> List[int]:
        """Get all request indices in tree order (respecting folder nesting)."""
        indices = []
        self._collect_indices("", indices)
        return indices

    def _collect_indices(self, parent: str, indices: list):
        for iid in self.tree.get_children(parent):
            if "request" in self.tree.item(iid, "tags"):
                if iid in self._iid_to_index:
                    indices.append(self._iid_to_index[iid])
            elif "folder" in self.tree.item(iid, "tags"):
                self._collect_indices(iid, indices)

    # ─── Event Handlers ──────────────────────────────────────────────────

    def _on_select(self, event=None):
        """Handle selection change — only trigger for requests, not folders."""
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        if "request" in self.tree.item(iid, "tags"):
            self.gui.on_select_item(event)

    def _on_right_click(self, event):
        """Show context menu on right-click."""
        iid = self.tree.identify_row(event.y)
        if not iid:
            # Right-click on empty area — offer to create folder
            menu = tk.Menu(self.gui, tearoff=0)
            menu.add_command(label="New Folder", command=lambda: self._create_folder(""))
            menu.tk_popup(event.x_root, event.y_root)
            return

        self.tree.selection_set(iid)
        menu = tk.Menu(self.gui, tearoff=0)

        if "folder" in self.tree.item(iid, "tags"):
            menu.add_command(label="New Request Here", command=lambda: self._new_request_in_folder(iid))
            menu.add_command(label="New Sub-Folder", command=lambda: self._create_folder(iid))
            menu.add_command(label="Rename Folder", command=lambda: self._rename_folder(iid))
            menu.add_command(label="Delete Folder", command=lambda: self._delete_folder(iid))
        else:
            menu.add_command(label="Duplicate", command=lambda: self._duplicate_request(iid))
            menu.add_command(label="Move to Folder...", command=lambda: self._move_to_folder(iid))
            menu.add_command(label="Delete", command=lambda: self._delete_request(iid))

        menu.tk_popup(event.x_root, event.y_root)

    def _create_folder(self, parent_iid: str):
        name = simpledialog.askstring("New Folder", "Folder name:")
        if name and name.strip():
            self.add_folder(name.strip(), parent_iid)

    def _rename_folder(self, iid: str):
        current = self.tree.item(iid, "text").replace("📁 ", "")
        name = simpledialog.askstring("Rename Folder", "New name:", initialvalue=current)
        if name and name.strip():
            self.tree.item(iid, text=f"📁 {name.strip()}")

    def _delete_folder(self, iid: str):
        children = self.tree.get_children(iid)
        if children:
            if not messagebox.askyesno("Delete Folder", "This folder has items. Delete everything inside?"):
                return
            # Remove all request indices inside
            self._remove_requests_recursive(iid)
        self.tree.delete(iid)
        self._rebuild_index_maps()

    def _remove_requests_recursive(self, parent_iid: str):
        """Remove requests from ctrl.requests for all items under a folder."""
        indices_to_remove = []
        self._collect_indices(parent_iid, indices_to_remove)
        # Remove in reverse order to maintain index validity
        for idx in sorted(indices_to_remove, reverse=True):
            if idx < len(self.gui.ctrl.requests):
                self.gui.ctrl.requests.pop(idx)
        self.gui.ctrl.last_index = None

    def _new_request_in_folder(self, folder_iid: str):
        """Create a new empty request inside a folder."""
        new_data = {
            "name": "New Request",
            "method": "GET",
            "url": "",
            "headers": {},
            "body_bytes": b"",
            "prerequest_script": "",
            "test_script": "",
        }
        self.gui.ctrl.requests.append(new_data)
        new_index = len(self.gui.ctrl.requests) - 1
        iid = self.add_request(new_index, "New Request", parent_iid=folder_iid)
        self.tree.selection_set(iid)
        self.gui.ctrl.last_index = new_index
        self.gui.ctrl.handle_selection(self.gui)

    def _duplicate_request(self, iid: str):
        """Duplicate the request at this tree node."""
        if iid not in self._iid_to_index:
            return
        import copy
        idx = self._iid_to_index[iid]
        original = self.gui.ctrl.requests[idx]
        clone = copy.deepcopy(original)
        clone["name"] = (clone.get("name") or "") + " (copy)"

        self.gui.ctrl.requests.append(clone)
        new_index = len(self.gui.ctrl.requests) - 1
        display = clone["name"] if clone["name"] else f"{clone.get('method', 'GET')} {clone.get('url', '')}"

        # Insert after the original in the same parent
        parent_iid = self.tree.parent(iid)
        new_iid = self.tree.insert(parent_iid, self.tree.index(iid) + 1, text=display, tags=("request",))
        self._iid_to_index[new_iid] = new_index
        self._index_to_iid[new_index] = new_iid

        self.tree.selection_set(new_iid)
        self.gui.ctrl.last_index = new_index
        self.gui.ctrl.handle_selection(self.gui)

    def _delete_request(self, iid: str):
        """Delete a single request."""
        if iid not in self._iid_to_index:
            return
        idx = self._iid_to_index[iid]
        if idx < len(self.gui.ctrl.requests):
            self.gui.ctrl.requests.pop(idx)
        self.tree.delete(iid)
        self.gui.ctrl.last_index = None
        self._rebuild_index_maps()

    def _move_to_folder(self, iid: str):
        """Move a request to a different folder via a selection dialog."""
        folders = self._get_all_folders()
        if not folders:
            messagebox.showinfo("Move", "No folders exist. Create a folder first.")
            return

        # Simple dialog to pick folder
        folder_names = ["(Root)"] + [self.tree.item(f, "text").replace("📁 ", "") for f in folders]
        folder_iids = [""] + folders

        win = tk.Toplevel(self.gui)
        win.title("Move to Folder")
        win.transient(self.gui)
        win.grab_set()

        ttk.Label(win, text="Select destination folder:").pack(padx=10, pady=(10, 5))
        listbox = tk.Listbox(win, height=min(10, len(folder_names)))
        for name in folder_names:
            listbox.insert(tk.END, name)
        listbox.pack(padx=10, pady=5, fill=tk.BOTH, expand=True)

        def on_ok():
            sel = listbox.curselection()
            if not sel:
                win.destroy()
                return
            target_iid = folder_iids[sel[0]]
            win.destroy()
            # Move in tree
            self.tree.move(iid, target_iid, "end")

        ttk.Button(win, text="Move", command=on_ok).pack(padx=10, pady=10)

    def _get_all_folders(self, parent: str = "") -> List[str]:
        """Recursively collect all folder iids."""
        folders = []
        for iid in self.tree.get_children(parent):
            if "folder" in self.tree.item(iid, "tags"):
                folders.append(iid)
                folders.extend(self._get_all_folders(iid))
        return folders

    # ─── Export Helper ────────────────────────────────────────────────────

    def get_tree_structure(self) -> List[Dict[str, Any]]:
        """
        Returns the tree as a nested structure for export:
        [
            {"type": "folder", "name": "...", "children": [...]},
            {"type": "request", "index": 0},
            ...
        ]
        """
        return self._export_children("")

    def _export_children(self, parent: str) -> List[Dict[str, Any]]:
        result = []
        for iid in self.tree.get_children(parent):
            if "folder" in self.tree.item(iid, "tags"):
                name = self.tree.item(iid, "text").replace("📁 ", "")
                children = self._export_children(iid)
                result.append({"type": "folder", "name": name, "children": children})
            elif "request" in self.tree.item(iid, "tags"):
                if iid in self._iid_to_index:
                    result.append({"type": "request", "index": self._iid_to_index[iid]})
        return result
