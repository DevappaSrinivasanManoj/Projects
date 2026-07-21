import json
from pathlib import Path
from tkinter import simpledialog, messagebox

class ExportHandler:
    @staticmethod
    def run_export(gui, eng_module):
        """
        Gathers all current requests from the controller, saves them 
        to a session.jsonl file, and exports as a Postman Collection JSON
        preserving folder structure from the tree sidebar.
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
            # 2. Get tree structure and requests
            tree_structure = gui._tree_sidebar.get_tree_structure()
            current_requests = gui.ctrl.get_all()
            session_file = Path(gui.folder) / "session.jsonl"

            # 3. Also write session.jsonl for backward compatibility
            with open(session_file, "w", encoding="utf-8") as f:
                for req in current_requests:
                    export_data = req.copy()
                    if not export_data.get("name"):
                        export_data["name"] = f"{req.get('method', 'GET')} {req.get('url', '')}"
                    body = export_data.get("body_bytes", b"")
                    if isinstance(body, bytes):
                        export_data["body_bytes"] = body.decode("utf-8", errors="replace")
                    f.write(json.dumps(export_data) + "\n")

            # 4. Export with folder structure using export_utils
            from export_utils import handle_full_postman_export
            from temp_var_store import TempVarStore, TEMP_VARS_FILENAME

            output_path = handle_full_postman_export(
                folder=gui.folder,
                collection_name=collection_name,
                session_path=session_file,
                temp_vars_filename=TEMP_VARS_FILENAME,
                temp_var_store_cls=TempVarStore,
                tree_structure=tree_structure,
                requests=current_requests,
            )

            messagebox.showinfo("Export Success", f"Postman collection created successfully at:\n{output_path}")

        except Exception as e:
            messagebox.showerror("Export Failed", f"An error occurred during export:\n{str(e)}")
