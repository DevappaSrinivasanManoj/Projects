import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional


def _build_postman_item(req: Dict[str, Any]) -> Dict[str, Any]:
    """Build a single Postman item dict from a request."""
    method = req.get("method", "GET").upper()
    body_str = req.get("body_bytes", "")
    if isinstance(body_str, bytes):
        body_str = body_str.decode("utf-8", errors="replace")

    item = {
        "name": req.get("name", f"{method} {req.get('url', '')}"),
        "request": {
            "method": method,
            "header": [{"key": k, "value": str(v)} for k, v in req.get("headers", {}).items()],
            "url": {"raw": req.get("url", ""), "host": [req.get("url", "")]}
        },
        "response": []
    }

    if method in ["POST", "PUT", "PATCH", "DELETE"] and body_str:
        item["request"]["body"] = {
            "mode": "raw",
            "raw": body_str,
            "options": {"raw": {"language": "json"}}
        }

    # Export scripts as Postman event array
    events = []
    prerequest_script = req.get("prerequest_script", "")
    test_script = req.get("test_script", "")
    if prerequest_script and prerequest_script.strip():
        events.append({
            "listen": "prerequest",
            "script": {
                "exec": prerequest_script.split("\n"),
                "type": "text/javascript"
            }
        })
    if test_script and test_script.strip():
        events.append({
            "listen": "test",
            "script": {
                "exec": test_script.split("\n"),
                "type": "text/javascript"
            }
        })
    if events:
        item["event"] = events

    return item


def _build_items_from_tree(tree_structure: List[Dict[str, Any]], requests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build nested Postman items from a tree structure.
    tree_structure is like:
    [
        {"type": "folder", "name": "...", "children": [...]},
        {"type": "request", "index": 0},
    ]
    """
    items = []
    for node in tree_structure:
        if node["type"] == "folder":
            folder_item = {
                "name": node["name"],
                "item": _build_items_from_tree(node.get("children", []), requests)
            }
            items.append(folder_item)
        elif node["type"] == "request":
            idx = node["index"]
            if idx < len(requests):
                items.append(_build_postman_item(requests[idx]))
    return items


def handle_full_postman_export(folder, collection_name, session_path, temp_vars_filename, temp_var_store_cls,
                               tree_structure: Optional[List[Dict[str, Any]]] = None,
                               requests: Optional[List[Dict[str, Any]]] = None):
    """
    Performs the full conversion to Postman Collection JSON.
    If tree_structure is provided, exports with folder hierarchy.
    Otherwise falls back to flat session.jsonl parsing.
    """
    items = []

    if tree_structure is not None and requests is not None:
        # Export with folder structure
        items = _build_items_from_tree(tree_structure, requests)
    elif session_path.exists():
        # Flat fallback: parse session.jsonl
        with open(session_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                req = json.loads(line)
                items.append(_build_postman_item(req))

    # Build the final Postman structure
    collection = {
        "info": {
            "name": collection_name,
            "_postman_id": f"export-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "description": f"Exported via export_utils",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
        },
        "item": items
    }

    # Inject variables from store
    try:
        store = temp_var_store_cls(folder / temp_vars_filename)
        vars_arr = store.to_postman_variables()
        if vars_arr:
            collection["variable"] = vars_arr
    except:
        pass

    # Write to disk
    out_path = folder / f"{collection_name.replace(' ', '_')}.postman_collection.json"
    out_path.write_text(json.dumps(collection, indent=2), encoding="utf-8")
    
    return out_path