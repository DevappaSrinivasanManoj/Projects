import json
import tkinter as tk

class SessionController:
    def __init__(self):
        self.requests = []
        self.last_index = None

    def load_initial_data(self, items):
        """Initializes the store when a collection is imported."""
        self.requests = [dict(i) for i in items]

    def handle_selection(self, gui):
        """Saves current UI data and loads the selected request's data."""
        # 1. Save UI state to the request we are leaving
        if self.last_index is not None:
            self.requests[self.last_index].update({
                "name": gui.ent_name.get().strip(),
                "method": gui.method_var.get(),
                "url": gui.ent_url.get(),
                "headers": gui._parse_headers_from_text(gui.txt_headers.get("1.0", "end-1c")),
                "body_bytes": gui.txt_payload.get("1.0", "end-1c").encode("utf-8"),
                "prerequest_script": gui.txt_prerequest.get("1.0", "end-1c"),
                "test_script": gui.txt_tests.get("1.0", "end-1c"),
            })

        # 2. Update the tracker to the new selection
        selection = gui.lst_items.curselection()
        if not selection: 
            return
        self.last_index = selection[0]
        
        # 3. Load the data for the new request into the UI
        data = self.requests[self.last_index]
        
        # Clear and load the name field
        gui.ent_name.delete(0, tk.END)
        gui.ent_name.insert(0, data.get("name", ""))
        
        # Load other fields
        gui.method_var.set(data.get("method", "GET"))
        gui.ent_url.delete(0, tk.END)
        gui.ent_url.insert(0, data.get("url", ""))
        
        # Load HEADERS
        gui.txt_headers.delete("1.0", tk.END)
        headers = data.get("headers", {})
        if headers:
            headers_text = "\n".join(f"{k}: {v}" for k, v in headers.items())
            gui.txt_headers.insert(tk.END, headers_text)
        gui._colorize_headers()
        
        gui.txt_payload.delete("1.0", tk.END)
        body = data.get("body_bytes", b"")
        if isinstance(body, bytes):
            gui.txt_payload.insert(tk.END, body.decode("utf-8", errors="replace"))
        else:
            gui.txt_payload.insert(tk.END, str(body))
        gui._colorize_json(gui.txt_payload)

        # Load scripts
        gui.txt_prerequest.delete("1.0", tk.END)
        gui.txt_prerequest.insert(tk.END, data.get("prerequest_script", ""))
        gui.txt_tests.delete("1.0", tk.END)
        gui.txt_tests.insert(tk.END, data.get("test_script", ""))

        try:
            snap = data.get("last_response")
            if snap:
                gui._load_response_snapshot(snap)
            else:
                gui._clear_response_view()
        except Exception:
            pass

    def get_all(self):
        return self.requests
