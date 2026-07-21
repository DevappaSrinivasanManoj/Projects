import tkinter as tk

class SidebarManager:
    @staticmethod
    def sync_new_request(gui):
        """Captures UI state for a NEW entry and adds it to the tree."""
        new_data = {
            "name": gui.ent_name.get().strip(),
            "method": gui.method_var.get(),
            "url": gui.ent_url.get().strip() or "New Request",
            "headers": gui._parse_headers_from_text(gui.txt_headers.get("1.0", "end-1c")),
            "body_bytes": gui.txt_payload.get("1.0", "end-1c").encode("utf-8"),
            "prerequest_script": gui.txt_prerequest.get("1.0", "end-1c"),
            "test_script": gui.txt_tests.get("1.0", "end-1c"),
        }
        gui.ctrl.requests.append(new_data)
        
        # DISPLAY LOGIC: Name only if it exists
        display_name = new_data["name"] if new_data["name"] else f"{new_data['method']} {new_data['url']}"
        
        new_index = len(gui.ctrl.requests) - 1
        # Add to the currently selected folder (or root)
        parent_iid = gui._tree_sidebar.get_selected_folder()
        gui._tree_sidebar.add_request(new_index, display_name, parent_iid=parent_iid)
        gui._tree_sidebar.selection_set(new_index)
        gui.ctrl.last_index = new_index

    @staticmethod
    def refresh_sidebar_label(gui):
        """FORCED UPDATE: Triggered by Rename button. Shows ONLY the name."""
        selection = gui.lst_items.curselection()
        if not selection:
            return
            
        idx = selection[0]
        
        # Get current UI values
        name = gui.ent_name.get().strip()
        method = gui.method_var.get()
        url = gui.ent_url.get().strip() or "New Request"
        
        # If 'name' has text, we ONLY show that text.
        display_text = name if name else f"{method} {url}"
        
        # Update the tree item text
        gui._tree_sidebar.update_request_text(idx, display_text)
        
        # Update the data store
        if gui.ctrl.last_index is not None:
            gui.ctrl.requests[gui.ctrl.last_index]["name"] = name
