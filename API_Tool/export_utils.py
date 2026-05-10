import json
from datetime import datetime
from pathlib import Path

def handle_full_postman_export(folder, collection_name, session_path, temp_vars_filename, temp_var_store_cls):
    """
    Performs the full conversion from session.jsonl to Postman Collection JSON.
    """
    items = []
    
    # 1. Parse session log and build items
    if session_path.exists():
        with open(session_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip(): continue
                req = json.loads(line)
                
                method = req.get("method", "GET").upper()
                body_str = req.get("body_bytes", "")
                
                item = {
                    "name": req.get("name", f"{method} {req.get('url', '')}"),
                    "request": {
                        "method": method,
                        "header": [{"key": k, "value": str(v)} for k, v in req.get("headers", {}).items()],
                        "url": {"raw": req.get("url", ""), "host": [req.get("url", "")]}
                    },
                    "response": []
                }

                # FIX: Ensure POST/PUT payloads are included
                if method in ["POST", "PUT", "PATCH", "DELETE"] and body_str:
                    item["request"]["body"] = {
                        "mode": "raw",
                        "raw": body_str,
                        "options": {"raw": {"language": "json"}}
                    }
                items.append(item)

    # 2. Build the final Postman structure
    collection = {
        "info": {
            "name": collection_name,
            "_postman_id": f"export-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "description": f"Exported via export_utils",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
        },
        "item": items
    }

    # 3. Inject variables from store
    try:
        store = temp_var_store_cls(folder / temp_vars_filename)
        vars_arr = store.to_postman_variables()
        if vars_arr:
            collection["variable"] = vars_arr
    except:
        pass

    # 4. Write to disk
    out_path = folder / f"{collection_name.replace(' ', '_')}.postman_collection.json"
    out_path.write_text(json.dumps(collection, indent=2), encoding="utf-8")
    
    return out_path