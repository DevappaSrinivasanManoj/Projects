import json
from pathlib import Path
from tkinter import simpledialog, messagebox

class ExportHandler:
    @staticmethod
    def run_export(gui, eng_module):
        """
        Gathers all current requests from the controller, saves them 
        to a session.jsonl file, and then uses the engine to convert 
        that file into a Postman Collection JSON.
        """
        # 1. Ask the user for the name of the new Postman Collection
        collection_name = simpledialog.askstring(
            "Export Postman", 
            "Enter name for the Postman Collection:", 
            initialvalue="Session Export"
        )
        if not collection_name:
            return

        try:
            # 2. Get the latest data from the SessionController
            current_requests = gui.ctrl.get_all()
            session_file = Path(gui.folder) / "session.jsonl"
            
            with open(session_file, "w", encoding="utf-8") as f:
                for req in current_requests:
                    export_data = req.copy()
                    
                    # Ensure name fallback
                    if not export_data.get("name"):
                        export_data["name"] = f"{req.get('method', 'GET')} {req.get('url', '')}"
                    
                    # Convert body_bytes to string for JSONL compatibility
                    # This ensures the POST payload is preserved in the intermediate file
                    body = export_data.get("body_bytes", b"")
                    if isinstance(body, bytes):
                        export_data["body_bytes"] = body.decode("utf-8", errors="replace")
                    
                    f.write(json.dumps(export_data) + "\n")
            
            # 3. Call the engine to perform the Postman Schema conversion
            output_path = eng_module.export_session_jsonl_to_postman(
                gui.folder, 
                collection_name=collection_name, 
                delete_temp_vars=True
            )
            
            messagebox.showinfo("Export Success", f"Postman collection created successfully at:\n{output_path}")
            
        except Exception as e:
            messagebox.showerror("Export Failed", f"An error occurred during export:\n{str(e)}")