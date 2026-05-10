import tkinter as tk

class SidebarManager:
    @staticmethod
    def sync_new_request(gui):
        """Captures UI state for a NEW entry."""
        new_data = {
            "name": gui.ent_name.get().strip(),
            "method": gui.method_var.get(),
            "url": gui.ent_url.get().strip() or "New Request",
            "headers": gui._parse_headers_from_text(gui.txt_headers.get("1.0", "end-1c")),
            "body_bytes": gui.txt_payload.get("1.0", "end-1c").encode("utf-8")
        }
        gui.ctrl.requests.append(new_data)
        
        # DISPLAY LOGIC: Name only if it exists
        display_name = new_data["name"] if new_data["name"] else f"{new_data['method']} {new_data['url']}"
        gui.lst_items.insert(tk.END, display_name)
        
        new_index = len(gui.ctrl.requests) - 1
        gui.lst_items.selection_clear(0, tk.END)
        gui.lst_items.selection_set(new_index)
        gui.ctrl.last_index = new_index

    @staticmethod
    def refresh_sidebar_label(gui):
        """FORCED UPDATE: Triggered by Rename button. Shows ONLY the name."""
        selection = gui.lst_items.curselection()
        if not selection: return
            
        idx = selection[0]
        
        # Get current UI values
        name = gui.ent_name.get().strip()
        method = gui.method_var.get()
        url = gui.ent_url.get().strip() or "New Request"
        
        # --- THE FIX ---
        # If 'name' has text, we ONLY show that text. 
        # We do NOT append method or URL.
        display_text = name if name else f"{method} {url}"
        
        # Update the visual list
        gui.lst_items.delete(idx)
        gui.lst_items.insert(idx, display_text)
        gui.lst_items.selection_set(idx)
        
        # Update the data store
        if gui.ctrl.last_index is not None:
            gui.ctrl.requests[gui.ctrl.last_index]["name"] = name