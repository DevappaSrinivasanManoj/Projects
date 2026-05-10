#!/usr/bin/env python3
"""
API Engine: urllib-based HTTP, cURL parsing, Postman parsing, logging, session export.
- Standard library only (validator optionally uses 'jsonschema' if present, via validate_schema.py).
- RAM-safe practices and flush-logging.
- Preserves original CLI interactive flow.
- Global DISABLE_SSL toggle (behaves like Postman's "Disable SSL").

Schema validation:
- URL → canonical schema base filename (ignoring query and dynamic segments like {id}, numbers, UUIDs)
- Status-specific lookup: ./schemas/<base>_<status>.txt, else fallback to ./schemas/<base>.txt
- Validates JSON responses using validate_schema.py
- Logs "SCHEMA VALIDATION" block and returns structured result.

DIFF (pairwise JSON comparison support):
- Thin wrapper around diff_engine.diff_json()
- Uniform "DIFF" log block
- Optional CLI toggle to compare consecutive JSON responses (1→2, 3→4, …)

NEW (Collection Variables - crash resilient):
- Uses TempVarStore at ./temp.collection.vars.json
- Renders {{var}} in URL, headers (values), and textual body before sending
- During export, injects variables into collection["variable"] and deletes temp vars file on success
- Works in scratchpad mode (no collection loaded)

NEW (Per-request extractors for chaining):
- Store mappings to pull values from a response (JSON path or Header) and set collection variables
- GUI can add mappings via “Set Collection Variables…” popup
- Runtime automatically applies mappings after each response
- Export embeds mappings per item under vendor field "x-apitool-extract" (Postman ignores; our tool re-loads)
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime
import logging
from typing import Dict, List, Optional, Any, Tuple
import shlex
import ssl
import re
import export_utils

# Try to import the local validator module (stdlib-first)
try:
    import validate_schema as vs
except Exception:
    vs = None

# DIFF engine
try:
    import diff_engine as de
except Exception:
    de = None

# --- NEW: Temp var store for {{var}} -----------------------------------------
from temp_var_store import TempVarStore, TEMP_VARS_FILENAME
# --- BEGIN ADD: extractor sidecar filename ---
_EXTRACTORS_INDEX_FILENAME = "extractors.index.json"
# --- END ADD: extractor sidecar filename ---


# --- NEW: per-request extractor map file -------------------------------------
EXTRACTOR_MAP_FILENAME = "extractors.map.json"  # stored in working folder


# ------------------------------ Global settings ------------------------------
DISABLE_SSL: bool = False

# -- NEW: per-request extractor cache (in-memory) + sidecar path --
_REQUEST_EXTRACTORS: Dict[str, List[Dict[str, Any]]] = {}
_EXTRACTORS_FILE = "extractors.map.json"
def _req_key(method: str, template_url: str, item_path: Optional[str]) -> str:
    return f"{item_path or ''}||{method.upper()}||{template_url.strip()}"


def set_disable_ssl(flag: bool) -> None:
    global DISABLE_SSL
    DISABLE_SSL = bool(flag)


# ------------------------------- Logging (flush) -----------------------------
def configure_logger(log_file: Path) -> logging.Logger:
    logger = logging.getLogger("api_tool_engine")
    logger.setLevel(logging.INFO)
    already = False
    for h in logger.handlers:
        if isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == str(log_file):
            already = True
            break
        if hasattr(h, "stream") and getattr(h.stream, "name", "") == str(log_file):
            already = True
            break
    if not already:
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fmt = logging.Formatter("%(message)s")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger

def log_block(logger: logging.Logger, title: str, lines: List[str]) -> None:
    ts = datetime.now().isoformat()
    sep = "=" * 80
    logger.info(f"{sep}\n[{ts}] {title}\n{sep}\n" + "\n".join(lines) + "\n")
    for h in logger.handlers:
        try:
            h.flush()
        except Exception:
            pass


# ------------------------- File helpers (CLI convenience) --------------------
def prompt_yes_no_change(prompt: str) -> bool:
    while True:
        choice = input(f"{prompt} (press 1 to change, 2 to continue): ").strip()
        if choice == "1": return True
        if choice == "2": return False
        print("Please press 1 or 2.")

def create_empty_file(path: Path) -> None:
    path.write_text("", encoding="utf-8")
    print(f"Created empty file: {path}")
    input(f"Edit '{path.name}' now, save it, then press Enter to continue...")

def read_url_file(path: Path) -> str:
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise ValueError(f"'{path.name}' is empty; please enter a URL and save.")
    return content

def parse_headers_file(path: Path) -> Dict[str, str]:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw: return {}
    if raw.startswith("{") and raw.endswith("}"):
        try:
            obj = json.loads(raw)
            return {str(k): str(v) for k, v in obj.items()}
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {path.name}: {e}")
    headers: Dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"): continue
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip()] = v.strip()
        else:
            parts = line.split(None, 1)
            if len(parts) == 2:
                headers[parts[0]] = parts[1]
    return headers

def read_payload_file(path: Path) -> bytes:
    raw = path.read_text(encoding="utf-8")
    return raw.encode("utf-8")


# ------------------------------------ SSL ------------------------------------
def build_ssl_context(disable_ssl: bool = False) -> Optional[ssl.SSLContext]:
    if not disable_ssl: return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# ----------------------------------- HTTP ------------------------------------
def _sanitize_url(url: str) -> str:
    """Percent-encode unsafe characters in the query string (e.g. spaces)."""
    parsed = urllib.parse.urlsplit(url)
    if not parsed.query:
        return url
    # Re-encode the query: parse it, then urlencode with quote_via to handle spaces etc.
    params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    safe_query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, safe_query, parsed.fragment))

def send_request(method: str, url: str, headers: Dict[str, str], body: bytes, timeout: float = 60.0
) -> Tuple[int, str, Dict[str, str], bytes]:
    url = _sanitize_url(url)
    req = urllib.request.Request(url=url, data=(body if body else None), headers=headers, method=method.upper())
    context = build_ssl_context(DISABLE_SSL)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            status = getattr(resp, "status", 200)
            reason = getattr(resp, "reason", "")
            resp_headers = dict(resp.headers.items())
            resp_body = resp.read() or b""
            return status, reason, resp_headers, resp_body
    except urllib.error.HTTPError as e:
        status = e.code
        reason = e.reason
        resp_headers = dict(e.headers.items()) if e.headers else {}
        resp_body = e.read() or (str(e).encode("utf-8"))
        return status, str(reason), resp_headers, resp_body
    except urllib.error.URLError as e:
        return 0, f"URLError: {e.reason}", {}, (str(e).encode("utf-8"))
    except Exception as e:
        return 0, f"Exception: {e}", {}, (str(e).encode("utf-8"))


# -------------------------------- Postman parsing -----------------------------
def postman_headers_to_dict(arr: List[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for h in (arr or []):
        key = h.get("key") or h.get("name")
        val = h.get("value") or ""
        if key: out[str(key)] = str(val)
    return out

def postman_url_to_str(url_obj: Any) -> str:
    if isinstance(url_obj, str): return url_obj
    if isinstance(url_obj, dict):
        raw = url_obj.get("raw")
        if raw: return str(raw)
        protocol = url_obj.get("protocol", "http")
        host = url_obj.get("host", [])
        host_str = ".".join(host) if isinstance(host, list) else str(host or "")
        path_parts = url_obj.get("path", [])
        path_str = "/".join(path_parts) if isinstance(path_parts, list) else str(path_parts or "")
        query_parts = url_obj.get("query", [])
        qs = urllib.parse.urlencode({q.get("key"): q.get("value", "") for q in query_parts if q.get("key")})
        return f"{protocol}://{host_str}/{path_str}" + (f"?{qs}" if qs else "")
    return ""

def extract_body_bytes_from_postman(req_obj: Dict[str, Any]) -> bytes:
    body = req_obj.get("body") or {}
    mode = body.get("mode")
    if mode == "raw":
        raw = body.get("raw", "")
        if isinstance(raw, str): return raw.encode("utf-8")
        return json.dumps(raw or "").encode("utf-8")
    elif mode == "urlencoded":
        kv = {e.get("key"): e.get("value", "") for e in (body.get("urlencoded") or []) if not e.get("disabled")}
        encoded = urllib.parse.urlencode(kv)
        return encoded.encode("utf-8")
    elif mode == "formdata":
        payload = [{"key": e.get("key"), "value": e.get("value")} for e in (body.get("formdata") or []) if not e.get("disabled")]
        return json.dumps(payload).encode("utf-8")
    else:
        return b""

def _read_item_extractors(it: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Read vendor-prefixed per-request extractor rules from a Postman item.
    """
    rules = it.get("x-apitool-extract") or []
    if isinstance(rules, list):
        # sanitize shape a bit
        out = []
        for r in rules:
            if not isinstance(r, dict): continue
            name = str(r.get("name") or "").strip()
            src = r.get("from")
            if src not in ("json", "header"): continue
            if src == "json":
                path = str(r.get("path") or "").strip()
                if name and path:
                    out.append({"name": name, "from": "json", "path": path})
            else:
                key = str(r.get("key") or "").strip()
                regex = r.get("regex")
                rr = {"name": name, "from": "header", "key": key}
                if isinstance(regex, str) and regex:
                    rr["regex"] = regex
                if name and key:
                    out.append(rr)
        return out
    return []


def flatten_postman_items(items: List[Dict[str, Any]], parent: str = "") -> List[Dict[str, Any]]:
    flattened: List[Dict[str, Any]] = []
    for it in items or []:
        # 1. Keep the 'clean_name' separate from the 'folder_path'
        clean_name = it.get("name") or "unnamed"
        folder_path = f"{parent}/{clean_name}" if parent else clean_name
        
        if "item" in it:
            # It's a folder, recurse deeper
            flattened.extend(flatten_postman_items(it["item"], parent=folder_path))
        else:
            # It's a request
            req = it.get("request")
            if not req: 
                continue
                
            # --- FIX: Define 'method' and 'url_str' BEFORE using them in _req_key ---
            method = (req.get("method") or "GET").upper()
            url_str = postman_url_to_str(req.get("url"))
            headers = postman_headers_to_dict(req.get("header", []))
            body_bytes = extract_body_bytes_from_postman(req)
            
            # Carry per-item extractors from Postman (x-apitool-extract)
            extractors = it.get("x-apitool-extract") or it.get("x_apitool_extract") or []

            # Add to the flattened list (Using 'clean_name' for the sidebar)
            flattened.append({
                "name": clean_name,  
                "path": folder_path, 
                "method": method,
                "url": url_str, 
                "headers": headers, 
                "body_bytes": body_bytes,
                "extractors": extractors
            })

            # Pull vendor extract rules into in-memory cache
            try:
                if extractors:
                    # Now 'method' and 'url_str' are safely defined
                    k = _req_key(method, url_str, folder_path)
                    _REQUEST_EXTRACTORS[k] = list(extractors)
            except Exception:
                pass

    return flattened
    

def load_collection_items(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("item", [])
    return flatten_postman_items(items)


# -- NEW: add extractor rule for a specific request and persist --
def add_request_extractor(folder: Path, item_path: Optional[str], method: str, template_url: str, rule: Dict[str, Any]) -> None:
    key = _req_key(method, template_url, item_path)
    arr = _REQUEST_EXTRACTORS.setdefault(key, [])
    arr.append(dict(rule))
    _save_extractors(folder)



# -- NEW: persist/restore extractors to a sidecar file in the folder --
def _extractors_path(folder: Path) -> Path:
    return folder / _EXTRACTORS_FILE

def _save_extractors(folder: Path) -> None:
    try:
        (_extractors_path(folder)).write_text(json.dumps(_REQUEST_EXTRACTORS, indent=2), encoding="utf-8")
    except Exception:
        pass

def _load_extractors(folder: Path) -> None:
    global _REQUEST_EXTRACTORS
    try:
        p = _extractors_path(folder)
        if p.exists():
            _REQUEST_EXTRACTORS = json.loads(p.read_text(encoding="utf-8")) or {}
            if not isinstance(_REQUEST_EXTRACTORS, dict):
                _REQUEST_EXTRACTORS = {}
    except Exception:
        _REQUEST_EXTRACTORS = {}




# ----------------------------------- Session ---------------------------------
def session_jsonl_path(folder: Path) -> Path:
    return folder / "session.jsonl"


# --- BEGIN ADD: extractor index helpers ---
def _extractors_index_path(folder: Path) -> Path:
    return folder / _EXTRACTORS_INDEX_FILENAME

def _load_extractors_index(folder: Path) -> Dict[str, list]:
    try:
        p = _extractors_index_path(folder)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        pass
    return {}
# --- END ADD: extractor index helpers ---


def append_request_to_session(folder: Path, method: str, url: str, headers: Dict[str, str], body_text: str) -> None:
    rec = {"method": method.upper(), "url": url, "headers": headers or {}, "body": body_text or "", "ts": datetime.now().isoformat()}
    p = session_jsonl_path(folder)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


# -------------------------- NEW: extractor map I/O ----------------------------
def _extractor_key(method: str, url: str) -> str:
    return f"{(method or '').upper()} {url or ''}"

def _extractor_map_path(folder: Path) -> Path:
    return folder / EXTRACTOR_MAP_FILENAME

def load_extractor_map(folder: Path) -> Dict[str, List[Dict[str, Any]]]:
    p = _extractor_map_path(folder)
    try:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Normalize: keys are "METHOD url", values are list of rule dicts
                out: Dict[str, List[Dict[str, Any]]] = {}
                for k, v in data.items():
                    if not isinstance(v, list): continue
                    clean: List[Dict[str, Any]] = []
                    for r in v:
                        if isinstance(r, dict) and "name" in r and "from" in r:
                            src = r.get("from")
                            if src == "json" and r.get("path"):
                                clean.append({"name": str(r["name"]), "from": "json", "path": str(r["path"])})
                            elif src == "header" and r.get("key"):
                                rr = {"name": str(r["name"]), "from": "header", "key": str(r["key"])}
                                if isinstance(r.get("regex"), str) and r.get("regex"):
                                    rr["regex"] = r["regex"]
                                clean.append(rr)
                    if clean:
                        out[str(k)] = clean
                return out
    except Exception:
        pass
    return {}

def save_extractor_map(folder: Path, m: Dict[str, List[Dict[str, Any]]]) -> None:
    try:
        _extractor_map_path(folder).write_text(json.dumps(m, indent=2), encoding="utf-8")
    except Exception:
        pass

def set_request_extract_rules(folder: Path, method: str, url: str, rules: List[Dict[str, Any]]) -> None:
    """
    Replace the extractor rules for the given (method,url) pair.
    """
    key = _extractor_key(method, url)
    m = load_extractor_map(folder)
    # Basic sanitize once more
    clean: List[Dict[str, Any]] = []
    for r in (rules or []):
        if not isinstance(r, dict): continue
        name = str(r.get("name") or "").strip()
        src = r.get("from")
        if src not in ("json", "header") or not name:
            continue
        if src == "json":
            path = str(r.get("path") or "").strip()
            if path:
                clean.append({"name": name, "from": "json", "path": path})
        else:
            keyh = str(r.get("key") or "").strip()
            if keyh:
                rr = {"name": name, "from": "header", "key": keyh}
                regex = r.get("regex")
                if isinstance(regex, str) and regex:
                    rr["regex"] = regex
                clean.append(rr)
    if clean:
        m[key] = clean
    else:
        # remove if empty
        if key in m:
            del m[key]
    save_extractor_map(folder, m)

def get_request_extract_rules(folder: Path, method: str, url: str) -> List[Dict[str, Any]]:
    m = load_extractor_map(folder)
    return list(m.get(_extractor_key(method, url), []))


# ---------------------- NEW: runtime extraction helpers -----------------------
_JSON_PATH_TOKEN_RE = re.compile(r"""
    (?:
        \.([A-Za-z0-9_\-]+)     # .key
      | \[(\d+)\]               # [index]
    )
""", re.VERBOSE)

def _json_pick(payload: Any, path: str) -> Optional[Any]:
    """
    Minimal '$.a.b[0]' style picker.
    Returns None if not found or path invalid.
    """
    if not isinstance(path, str) or not path.startswith("$"):
        return None
    cur: Any = payload
    # Strip leading '$'
    rest = path[1:]
    # Tokenize like .key and [index]
    for m in _JSON_PATH_TOKEN_RE.finditer(rest):
        key, idx = m.group(1), m.group(2)
        if key is not None:
            if not isinstance(cur, dict) or key not in cur:
                return None
            cur = cur[key]
        else:
            # index
            i = int(idx)
            if not isinstance(cur, list) or i < 0 or i >= len(cur):
                return None
            cur = cur[i]
    return cur

def _case_insensitive_get(headers: Dict[str, str], key: str) -> Optional[str]:
    kl = key.lower()
    for k, v in headers.items():
        if str(k).lower() == kl:
            return str(v)
    return None

def _safe_json_loads(body_bytes: bytes) -> Tuple[bool, Optional[Any], Optional[str]]:
    try:
        text = body_bytes.decode("utf-8", errors="replace")
        return True, json.loads(text), None
    except Exception as e:
        return False, None, str(e)


# -- NEW: tiny '$' path walker used by extractors --
def _pick_json_path(payload: Any, path: str) -> Optional[Any]:
    if not path or not path.startswith("$"): return None
    cur = payload
    # tokenize on . and [i]
    import re
    tokens = []
    s = path[2:] if path.startswith("$.") else path[1:]
    parts = re.split(r'\.(?![^[]*\])', s) if s else []
    for p in parts:
        while p:
            m = re.match(r'^([^\[\]]+)', p)
            if m:
                tokens.append(m.group(1)); p = p[m.end():]
            elif p.startswith('['):
                m = re.match(r'^\[(\d+)\]', p)
                if not m: return None
                tokens.append(int(m.group(1))); p = p[m.end():]
            else:
                break
    try:
        for t in tokens:
            if isinstance(t, int):
                if not isinstance(cur, list) or t >= len(cur): return None
                cur = cur[t]
            else:
                if not isinstance(cur, dict) or t not in cur: return None
                cur = cur[t]
        return cur
    except Exception:
        return None

def _get_header(headers: Dict[str, str], key: str) -> Optional[str]:
    lk = key.lower().strip()
    for k, v in (headers or {}).items():
        if k.lower() == lk: return v
    return None


def apply_extractors_for_request(
    folder: Path,
    method: str,
    template_url: str,
    status: int,
    headers: Dict[str, str],
    resp_body: bytes,
    logger: Optional[logging.Logger] = None,
    inline_rules: Optional[List[Dict[str, Any]]] = None
) -> List[Tuple[str, str]]:
    """
    Apply per-request extractor rules:
      - Rules saved in extractors.map.json keyed by (method, template_url)
      - Optional inline rules supplied by the caller (e.g., from imported collection item)
    Any extracted variables are saved to TempVarStore and logged.
    Returns list of (variable_name, value) actually saved.
    """
    saved: List[Tuple[str, str]] = []

    # Gather rules: map + inline
    rules = []
    rules.extend(get_request_extract_rules(folder, method, template_url))
    if inline_rules:
        rules.extend(inline_rules)

    if not rules:
        return saved

    # Prepare JSON payload (optional)
    ok, payload, perr = _safe_json_loads(resp_body)

    store = TempVarStore(folder / TEMP_VARS_FILENAME)

    for r in rules:
        try:
            name = str(r.get("name") or "").strip()
            src = r.get("from")
            if not name or src not in ("json", "header"):
                continue

            value: Optional[str] = None

            if src == "json":
                if not ok:
                    continue
                path = str(r.get("path") or "").strip()
                if not path:
                    continue
                found = _json_pick(payload, path)
                if found is None:
                    continue
                if isinstance(found, (str, int, float, bool)) or found is None:
                    value = "" if found is None else str(found)
                else:
                    # complex -> store as compact JSON
                    value = json.dumps(found, separators=(",", ":"), ensure_ascii=False)

            else:
                key = str(r.get("key") or "").strip()
                if not key:
                    continue
                hv = _case_insensitive_get(headers or {}, key)
                if hv is None:
                    continue
                regex = r.get("regex")
                if isinstance(regex, str) and regex:
                    mm = re.search(regex, hv)
                    if not mm:
                        continue
                    if mm.groups():
                        value = mm.group(1)
                    else:
                        value = mm.group(0)
                else:
                    value = hv

            if value is None:
                continue

            store.set(name, value)
            saved.append((name, value))
        except Exception:
            # swallow individual rule errors; keep going
            continue

    if saved:
        store.save()
        if logger:
            lines = [
                f"Request: {method.upper()} {template_url}",
                f"Status:  {status}",
                "Saved variables:"
            ]
            lines += [f" - {k} = {v}" for k, v in saved]
            log_block(logger, "VARIABLE EXTRACTORS", lines)

    return saved


# ------------------------------ cURL parsing ---------------------------------
def _parse_header_line(h: str) -> Tuple[str, str]:
    if ":" in h:
        k, v = h.split(":", 1)
        return k.strip(), v.strip()
    return h.strip(), ""

def parse_curl(curl_str: str, folder: Optional[Path] = None) -> Tuple[str, str, Dict[str, str], bytes]:
    tokens = shlex.split(curl_str)
    if tokens and tokens[0].lower() == "curl": tokens = tokens[1:]
    method: Optional[str] = None
    url: str = ""
    headers: Dict[str, str] = {}
    body_bytes: Optional[bytes] = None
    form_fields: List[Dict[str, str]] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("-X", "--request"):
            if i + 1 < len(tokens):
                method = tokens[i + 1].upper(); i += 2; continue
        if t.startswith("-X") and t != "-X":
            method = t[2:].upper(); i += 1; continue
        if t.startswith("--request="):
            method = t.split("=", 1)[1].upper(); i += 1; continue
        if t in ("-H", "--header"):
            if i + 1 < len(tokens):
                k, v = _parse_header_line(tokens[i + 1]); headers[k] = v; i += 2; continue
        if t.startswith("-H") and t != "-H":
            hdr = t[2:]
            if not hdr and i + 1 < len(tokens): hdr = tokens[i + 1]; i += 2
            else: i += 1
            k, v = _parse_header_line(hdr); headers[k] = v; continue
        if t.startswith("--header="):
            k, v = _parse_header_line(t.split("=", 1)[1]); headers[k] = v; i += 1; continue

        def _read_data_value(val: str) -> bytes:
            if val.startswith("@") and folder is not None:
                fp = folder / val[1:]
                if fp.exists(): return fp.read_bytes()
            return val.encode("utf-8")

        data_flags = ("-d", "--data", "--data-raw", "--data-binary")
        if t in data_flags:
            val = tokens[i + 1] if i + 1 < len(tokens) else ""
            i += 2 if i + 1 < len(tokens) else 1
            body_bytes = _read_data_value(val)
            if method is None: method = "POST"
            continue
        if any(t.startswith(df + "=") for df in data_flags):
            eq_val = t.split("=", 1)[1]
            body_bytes = _read_data_value(eq_val)
            if method is None: method = "POST"
            i += 1; continue
        if t.startswith("-d") and t != "-d":
            val = t[2:]
            body_bytes = _read_data_value(val)
            if method is None: method = "POST"
            i += 1; continue

        form_flags = ("-F", "--form")
        if t in form_flags:
            val = tokens[i + 1] if i + 1 < len(tokens) else ""
            i += 2 if i + 1 < len(tokens) else 1
            if "=" in val:
                k, v = val.split("=", 1)
                if v.startswith("@") and folder is not None:
                    fp = folder / v[1:]
                    if fp.exists(): v = fp.read_text(encoding="utf-8")
                form_fields.append({"key": k, "value": v})
            else:
                form_fields.append({"key": val, "value": ""})
            if method is None: method = "POST"
            continue
        if t.startswith("-F") and t != "-F":
            val = t[2:]
            if "=" in val:
                k, v = val.split("=", 1)
                if v.startswith("@") and folder is not None:
                    fp = folder / v[1:]
                    if fp.exists(): v = fp.read_text(encoding="utf-8")
                form_fields.append({"key": k, "value": v})
            else:
                form_fields.append({"key": val, "value": ""})
            if method is None: method = "POST"
            i += 1; continue
        if t.startswith("--form="):
            val = t.split("=", 1)[1]
            if "=" in val:
                k, v = val.split("=", 1)
                if v.startswith("@") and folder is not None:
                    fp = folder / v[1:]
                    if fp.exists(): v = fp.read_text(encoding="utf-8")
                form_fields.append({"key": k, "value": v})
            else:
                form_fields.append({"key": val, "value": ""})
            if method is None: method = "POST"
            i += 1; continue

        if t == "--url":
            if i + 1 < len(tokens): url = tokens[i + 1]; i += 2; continue
            i += 1; continue
        if t in ("--insecure", "-k"):
            i += 1; continue
        if not t.startswith("-"):
            url = t
            i += 1
            continue

    if form_fields and body_bytes is None:
        body_bytes = json.dumps(form_fields).encode("utf-8")
    if method is None:
        method = "POST" if body_bytes else "GET"
    return method, url, headers, (body_bytes or b"")


# ----------------------------- Schema validation ------------------------------
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")

def _is_dynamic_segment(seg: str) -> bool:
    if not seg: return False
    if seg.startswith("{") and seg.endswith("}"): return True
    if seg.isdigit(): return True
    if _UUID_RE.fullmatch(seg) is not None: return True
    return False

def canonical_schema_base_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or ""
    if path.endswith("/"): path = path[:-1]
    segments = [s for s in path.split("/") if s]
    filtered = [s for s in segments if not _is_dynamic_segment(s)]
    if not filtered: return "root"
    return "_".join(filtered)

def _is_json_content_type(headers: Dict[str, str]) -> bool:
    ct = ""
    for k, v in headers.items():
        if k.lower() == "content-type":
            ct = v.lower(); break
    return ("application/json" in ct) or ct.endswith("+json")

def _safe_json_loads(body_bytes: bytes) -> Tuple[bool, Optional[Any], Optional[str]]:
    try:
        text = body_bytes.decode("utf-8", errors="replace")
        return True, json.loads(text), None
    except Exception as e:
        return False, None, str(e)

def _pick_status_specific_schema(work_folder: Path, base: str, status: int) -> Tuple[Optional[Path], Optional[Path]]:
    schemas_dir = work_folder / "schemas"
    status_path = schemas_dir / f"{base}_{status}.txt"
    generic_path = schemas_dir / f"{base}.txt"
    return (status_path if status_path.exists() else None,
            generic_path if generic_path.exists() else None)

def validate_and_log_schema(
    url: str,
    status: int,
    headers: Dict[str, str],
    resp_body: bytes,
    work_folder: Path,
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    result = {"ran": False, "valid": False, "count": 0, "schema_path": None, "errors": [], "reason": ""}

    if not _is_json_content_type(headers):
        result["reason"] = "Skipped: non-JSON Content-Type"
        return result

    ok, payload, parse_err = _safe_json_loads(resp_body)
    if not ok:
        result["ran"] = True
        result["reason"] = f"Response body is not valid JSON: {parse_err}"
        if logger:
            log_block(logger, "SCHEMA VALIDATION", [
                f"URL: {url}",
                f"Status: {status}",
                f"Schema: (none)",
                f"Result: ❌ Parse error",
                f"Details: {parse_err}"
            ])
        return result

    base = canonical_schema_base_from_url(url)
    status_path, generic_path = _pick_status_specific_schema(work_folder, base, status)
    schema_path = status_path or generic_path
    result["schema_path"] = schema_path

    if schema_path is None:
        result["reason"] = f"No schema file: tried {base}_{status}.txt and {base}.txt"
        if logger:
            log_block(logger, "SCHEMA VALIDATION", [
                f"URL: {url}",
                f"Status: {status}",
                f"Schema: {base}_{status}.txt / {base}.txt",
                "Result: ⚠️ No schema file; validation skipped."
            ])
        return result

    try:
        schema_text = schema_path.read_text(encoding="utf-8")
        schema = json.loads(schema_text)
    except Exception as e:
        result["ran"] = True
        result["reason"] = f"Failed to load schema: {e}"
        if logger:
            log_block(logger, "SCHEMA VALIDATION", [
                f"URL: {url}",
                f"Status: {status}",
                f"Schema: {schema_path.name}",
                "Result: ❌ Failed to load/parse schema file",
                f"Details: {e}"
            ])
        return result

    errors_strs: List[str] = []
    try:
        if vs is not None:
            js_errors = vs.try_jsonschema_validate(payload, schema)
            if js_errors is None:
                built_errors = vs.validate_node(payload, schema, [], schema)
                errors_strs = [str(e) for e in built_errors]
            else:
                errors_strs = [str(e) for e in js_errors]
        else:
            if isinstance(payload, (dict, list)):
                errors_strs = []
            else:
                errors_strs = ["$: expected object/array, got scalar"]
    except Exception as e:
        result["ran"] = True
        result["reason"] = f"Validator error: {e}"
        if logger:
            log_block(logger, "SCHEMA VALIDATION", [
                f"URL: {url}",
                f"Status: {status}",
                f"Schema: {schema_path.name}",
                "Result: ❌ Validator crashed",
                f"Details: {e}"
            ])
        return result

    result["ran"] = True
    result["count"] = len(errors_strs)
    result["valid"] = (len(errors_strs) == 0)
    result["errors"] = errors_strs

    if logger:
        lines = [
            f"URL: {url}",
            f"Status: {status}",
            f"Schema: {schema_path.name}",
            f"Result: {'✅ VALID' if result['valid'] else f'❌ INVALID ({result['count']} issue(s))'}",
        ]
        if errors_strs:
            lines.append("Differences:")
            lines.extend(f" - {msg}" for msg in errors_strs)
        log_block(logger, "SCHEMA VALIDATION", lines)
    return result


# -- NEW: apply extractors for this request and persist variables --
def apply_extractors_and_save(
    folder: Path,
    item_path: Optional[str],
    method: str,
    template_url: str,
    status: int,
    headers: Dict[str, str],
    resp_body: bytes,
    logger: Optional[logging.Logger] = None
) -> None:
    key = _req_key(method, template_url, item_path)
    rules = _REQUEST_EXTRACTORS.get(key) or []
    if not rules: return
    text = resp_body.decode("utf-8", errors="replace") if resp_body else ""
    ok, payload, _ = _safe_json_loads(resp_body) if resp_body else (False, None, None)

    store = TempVarStore(folder / TEMP_VARS_FILENAME)
    captured: List[str] = []
    for r in rules:
        name = (r.get("name") or "").strip()
        if not name: continue
        val = None
        if r.get("from") == "json":
            path = r.get("path") or ""
            if ok and isinstance(payload, (dict, list)):
                v = _pick_json_path(payload, path)
                if v is not None:
                    val = v if isinstance(v, (str, int, float, bool)) else json.dumps(v, ensure_ascii=False)
        elif r.get("from") == "header":
            keyh = r.get("key") or ""
            hv = _get_header(headers, keyh)
            if hv is not None: val = hv
        if val is not None:
            store.set(name, val)
            captured.append(f"{name}={val}")
    if captured:
        store.save()
        if logger:
            log_block(logger, "EXTRACT", [
                f"Request: {method} {template_url}",
                "Captured:",
                *[f" - {c}" for c in captured]
            ])



# ---------------------------------- DIFF helpers ------------------------------
def run_diff(prev_json: Any, curr_json: Any) -> Dict[str, Any]:
    if de is None:
        return {"valid": True, "count": 0, "lines": ["(diff_engine not available)"], "stats": {}}
    return de.diff_json(prev_json, curr_json)

def log_diff_block(
    logger: logging.Logger,
    meta: Dict[str, Any],  # expects: url_a, status_a, url_b, status_b
    diff: Dict[str, Any]
) -> None:
    lines = [
        f"A: {meta.get('url_a', '')} (status {meta.get('status_a', '-')})",
        f"B: {meta.get('url_b', '')} (status {meta.get('status_b', '-')})",
        f"Result: {'✅ No differences' if diff.get('valid') else f'❌ DIFFERENCES ({diff.get('count', 0)})'}",
    ]
    if not diff.get("valid"):
        lines.append("Differences:")
        lines.extend(f" - {s}" for s in diff.get("lines", []))
    log_block(logger, "DIFF", lines)


# ----------------------------- Variable rendering -----------------------------
def _render_with_vars(folder: Path, url: str, headers: Dict[str, str], body: bytes
) -> Tuple[str, Dict[str, str], bytes]:
    """
    Apply collection variables to URL, headers (values), and textual body using TempVarStore.
    This function is called immediately before sending to ensure we pick up the latest edits.
    """
    store = TempVarStore(folder / TEMP_VARS_FILENAME)
    # URL
    url = store.render_text(url)
    # Headers
    headers = store.render_headers(headers)
    # Body (textual)
    if body:
        try:
            text = body.decode("utf-8")
            text = store.render_text(text)
            body = text.encode("utf-8")
        except Exception:
            pass
    return url, headers, body


# --- BEGIN ADD: runtime extractor helpers + apply function ---
def _case_insensitive_get(headers: Dict[str, str], key: str) -> str:
    if not headers or not key:
        return ""
    kl = key.lower()
    for k, v in headers.items():
        if str(k).lower() == kl:
            return str(v)
    return ""

def _json_pick(payload: Any, path: str) -> Any:
    """
    Minimal $-style path: $.a.b[0].c
    Supports dict keys with dots and list indices in [n].
    """
    if not isinstance(path, str) or not path.startswith("$"):
        return None
    cur = payload
    i = 1  # skip '$'
    token = ""
    while i < len(path):
        ch = path[i]
        if ch == ".":
            if token:
                if not isinstance(cur, dict) or token not in cur:
                    return None
                cur = cur[token]
                token = ""
            i += 1
        elif ch == "[":
            # flush pending token before index
            if token:
                if not isinstance(cur, dict) or token not in cur:
                    return None
                cur = cur[token]
                token = ""
            # read index
            j = path.find("]", i + 1)
            if j == -1:
                return None
            idx_str = path[i + 1:j]
            try:
                idx = int(idx_str)
            except ValueError:
                return None
            if not isinstance(cur, list) or idx < 0 or idx >= len(cur):
                return None
            cur = cur[idx]
            i = j + 1
        else:
            token += ch
            i += 1
    if token:
        if not isinstance(cur, dict) or token not in cur:
            return None
        cur = cur[token]
    return cur

def apply_extractors_and_save(
    folder: Path,
    method: str,
    template_url: str,
    status: int,
    headers: Dict[str, str],
    resp_body: bytes,
    logger: Optional[logging.Logger] = None
) -> None:
    """
    Looks up per-request rules from sidecar (extractors.index.json) by (METHOD + template_url),
    extracts values from the just-received response, writes them to TempVarStore, and logs.
    """
    # Load extractor sidecar
    try:
        idx_path = folder / _EXTRACTORS_INDEX_FILENAME
        rules_index = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    except Exception:
        rules_index = {}

    req_key = f"{(method or 'GET').upper()} {template_url or ''}"
    rules = rules_index.get(req_key, [])
    if not rules:
        return  # nothing to do

    # Prepare response material
    body_text = ""
    payload = None
    try:
        body_text = (resp_body or b"").decode("utf-8", errors="replace")
        payload = json.loads(body_text) if body_text.strip() else None
    except Exception:
        payload = None

    # Apply rules
    store = TempVarStore(folder / TEMP_VARS_FILENAME)
    set_count = 0
    lines = [f"Request: {req_key}", f"Status: {status}", "Captured:"]

    for rule in rules:
        name = str(rule.get("name") or "").strip()
        src = str(rule.get("from") or "json").strip().lower()
        value = None
        reason = ""
        if not name:
            continue
        if src == "json":
            path = str(rule.get("path") or "").strip()
            if payload is None or not path:
                reason = "no JSON or empty path"
            else:
                value = _json_pick(payload, path)
                if value is None:
                    reason = f"path not found: {path}"
        elif src == "header":
            key = str(rule.get("key") or "").strip()
            if not key:
                reason = "empty header key"
            else:
                value = _case_insensitive_get(headers or {}, key)
                if value == "":
                    reason = f"header not found: {key}"
        else:
            reason = f"unknown source: {src}"

        if value is None or value == "":
            lines.append(f" - {name}: (skipped) {reason}")
            continue

        # Normalize to string
        if isinstance(value, (dict, list)):
            val_str = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            val_str = str(value)
        store.set(name, val_str)
        set_count += 1
        lines.append(f" - {name} = {val_str}")

    if set_count:
        try:
            store.save()  # persist to disk
        except Exception as e:
            lines.append(f"Save error: {e}")

    if logger is not None:
        log_block(logger, "EXTRACTORS", lines)
# --- END ADD: runtime extractor helpers + apply function ---


# ------------------------------ CLI (interactive) -----------------------------
def run_cli_interactive(folder: Path) -> None:
    print(f"\nWorking folder: {folder.resolve()}")
    print(f"SSL verification: {'DISABLED' if DISABLE_SSL else 'ENABLED'}")
    log_file = folder / "logger.txt"
    logger = configure_logger(log_file)
    
    # -- NEW: restore extractors for this working folder --
    _load_extractors(folder)
    # Detect Postman collections


    # Detect Postman collections
    candidates = list(folder.glob("*.postman_collection.json")) or list(folder.glob("*.json"))
    coll_paths: List[Path] = []
    for p in candidates:
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            schema = (j.get("info", {}).get("schema") or "")
            if "postman" in str(schema).lower() or "item" in j:
                coll_paths.append(p)
        except Exception:
            continue

    chosen_coll: Optional[Path] = None
    items: List[Dict[str, Any]] = []
    if coll_paths:
        if len(coll_paths) == 1:
            chosen_coll = coll_paths[0]
        else:
            print("\nMultiple JSON files detected. Choose a Postman collection:")
            for i, cp in enumerate(coll_paths, start=1):
                print(f" {i}. {cp.name}")
            while True:
                sel = input("Enter number (or press Enter to skip selection): ").strip()
                if not sel: break
                if sel.isdigit() and 1 <= int(sel) <= len(coll_paths):
                    chosen_coll = coll_paths[int(sel) - 1]; break
                print("Invalid selection. Try again.")
    if chosen_coll:
        print(f"\nLoaded Postman collection: {chosen_coll.name}")
        try:
            items = load_collection_items(chosen_coll)
        except Exception as e:
            print(f"Failed to parse collection: {e}")
            items = []
        # Load collection-level variables into temp store (existing behavior)
        try:
            data = json.loads(chosen_coll.read_text(encoding="utf-8"))
            var_arr = data.get("variable", []) or []
            store = TempVarStore(folder / TEMP_VARS_FILENAME)
            store.clear()
            for v in var_arr:
                k = str(v.get("key") or v.get("name") or "").strip()
                val = "" if v.get("value") is None else str(v.get("value"))
                if k:
                    store.set(k, val)
            store.save()
            print(f"Imported {len(var_arr)} collection variable(s) into temp store.")
        except Exception:
            pass

    # DIFF: CLI toggle and pair buffer
    compare_enabled = False
    pending_diff: Optional[Dict[str, Any]] = None  # stores prev {"url","status","json"}

    while True:
        print("\nBelow are the different endpoints:")
        print(" 0. (Custom request not in the collection)")
        print(" 1. (Import cURL and fire)")
        if items:
            for idx, it in enumerate(items, start=2):
                print(f" {idx}. {it['method']:6s} {it['url']} [{it['path']}]")
        else:
            print(" (No Postman collection endpoints found in this folder.)")
        print(f"\nCompare consecutive responses: {'ON' if compare_enabled else 'OFF'} (CLI)")
        print("\nSelect an index number:")
        print(" - Pick an endpoint number to send a request")
        print(" - Or type 'C' to toggle Compare ON/OFF")
        print(" - Or type 'V' to view/edit variables (temp)")
        selection = input("> ").strip()

        if selection.lower() == "c":
            compare_enabled = not compare_enabled
            print(f"Compare is now {'ON' if compare_enabled else 'OFF'}.")
            pending_diff = None
            continue

        if selection.lower() == "v":
            # Tiny inline editor for variables (CLI convenience)
            store = TempVarStore(folder / TEMP_VARS_FILENAME)
            print("\nCurrent variables:")
            if store.data:
                for k, v in store.items():
                    print(f" - {k} = {v}")
            else:
                print(" (none)")
            while True:
                cmd = input("\n[V]iew, [S]et key=val, [D]elete key, [Q]uit: ").strip().lower()
                if cmd == "q": break
                elif cmd == "v":
                    store.load()
                    if store.data:
                        for k, v in store.items():
                            print(f" - {k} = {v}")
                    else:
                        print(" (none)")
                elif cmd == "s":
                    kv = input("Enter key=value: ").strip()
                    if "=" in kv:
                        k, v = kv.split("=", 1)
                        store.set(k.strip(), v)
                        store.save()
                        print("Saved.")
                elif cmd == "d":
                    k = input("Enter key to delete: ").strip()
                    store.delete(k)
                    store.save()
                    print("Deleted.")
                else:
                    print("Unknown command.")
            continue

        if not selection.isdigit():
            print("Please enter a valid number, 'C' for Compare, or 'V' for Variables.")
            continue
        choice = int(selection)

        method = "GET"; url = ""; headers: Dict[str, str] = {}; body: bytes = b""
        inline_rules: List[Dict[str, Any]] = []

        if choice == 0:
            method = input("Enter HTTP method (GET, POST, PUT, PATCH, DELETE, etc.): ").strip().upper() or "GET"
            url_file = folder / "url.txt"; create_empty_file(url_file)
            try: url = read_url_file(url_file)
            except ValueError as e: print(e); continue

            headers_file = folder / "headers.txt"; create_empty_file(headers_file)
            try: headers = parse_headers_file(headers_file)
            except ValueError as e: print(e); continue

            body_file = folder / "payload.txt"
            if method in {"POST", "PUT", "PATCH", "DELETE"}:
                create_empty_file(body_file); body = read_payload_file(body_file)
            else: body = b""

        elif choice == 1:
            curl_file = folder / "curl.txt"; create_empty_file(curl_file)
            curl_cmd = curl_file.read_text(encoding="utf-8").strip()
            if not curl_cmd:
                print("curl.txt is empty; please paste a cURL command and try again."); continue
            try: method, url, headers, body = parse_curl(curl_cmd, folder=folder)
            except Exception as e: print(f"Failed to parse cURL: {e}"); continue

            print(f"\nDerived URL:\n {url}")
            if prompt_yes_no_change("If any change needed in the URL"):
                url_file = folder / "url.txt"; create_empty_file(url_file)
                try: url = read_url_file(url_file)
                except ValueError as e: print(e); continue

            print("\nCurrent headers:")
            if headers:
                for k, v in headers.items(): print(f" {k}: {v}")
            else: print(" (none)")
            if prompt_yes_no_change("If any change needed in the headers"):
                headers_file = folder / "headers.txt"; create_empty_file(headers_file)
                try: headers = parse_headers_file(headers_file)
                except ValueError as e: print(e); continue

            needs_payload = (method in {"POST", "PUT", "PATCH", "DELETE"}) or (body and len(body) > 0)
            if needs_payload:
                print("\nCurrent payload:")
                print(body.decode("utf-8", errors="replace") if body else "(empty)")
                if prompt_yes_no_change("If any change needed in the payload"):
                    payload_file = folder / "payload.txt"; create_empty_file(payload_file)
                    body = read_payload_file(payload_file)
            else:
                body = b""

        else:
            if not items or choice < 2 or choice > (len(items) + 1):
                print("Index out of range. Try again."); continue
            it = items[choice - 2]
            method = it["method"]; url = it["url"]; headers = dict(it["headers"]); body = it["body_bytes"]
            inline_rules = it.get("extract", []) or []

            print(f"\nSelected URL:\n {url}")
            if prompt_yes_no_change("If any change needed in the URL"):
                url_file = folder / "url.txt"; create_empty_file(url_file)
                try: url = read_url_file(url_file)
                except ValueError as e: print(e); continue

            print("\nCurrent headers:")
            if headers:
                for k, v in headers.items(): print(f" {k}: {v}")
            else:
                print(" (none)")
            if prompt_yes_no_change("If any change needed in the headers"):
                headers_file = folder / "headers.txt"; create_empty_file(headers_file)
                try: headers = parse_headers_file(headers_file)
                except ValueError as e: print(e); continue

            needs_payload = (method in {"POST", "PUT", "PATCH", "DELETE"}) or (body and len(body) > 0)
            if needs_payload:
                print("\nCurrent payload:")
                print(body.decode("utf-8", errors="replace") if body else "(empty)")
                if prompt_yes_no_change("If any change needed in the payload"):
                    payload_file = folder / "payload.txt"; create_empty_file(payload_file)
                    body = read_payload_file(payload_file)
            else:
                body = b""

        # Apply variables before sending
        url, headers, body = _render_with_vars(folder, url, headers, body)

        # Send request
        timeout = 60.0; print("\nSending request...")
        status, reason, resp_headers, resp_body = send_request(method, url, headers, body, timeout=timeout)

        # Request summary
        print("\n=== REQUEST ===")
        print(f"{method} {url}")
        print("Headers:")
        if headers:
            for k, v in headers.items(): print(f" {k}: {v}")
        else:
            print(" (none)")
        if body:
            print("Body:"); print(body.decode("utf-8", errors="replace"))
        else:
            print("Body: (empty)")

        # Response summary
        print("\n=== RESPONSE ===")
        print(f"Status: {status} {reason}")
        print("Headers:")
        if resp_headers:
            for k, v in resp_headers.items(): print(f" {k}: {v}")
        else:
            print(" (none)")
        print("Body:")
        print(resp_body.decode("utf-8", errors="replace") if resp_body else "(empty)")

        # Logging
        req_lines = [
            f"REQUEST: {method} {url}",
            "Request Headers:",
            *(f" {k}: {v}" for k, v in headers.items()),
            "Request Body:",
            body.decode("utf-8", errors="replace") if body else "(empty)"
        ]
        log_block(logger, "HTTP REQUEST", req_lines)
        resp_lines = [
            f"STATUS: {status} {reason}",
            "Response Headers:",
            *(f" {k}: {v}" for k, v in resp_headers.items()),
            "Response Body:",
            resp_body.decode("utf-8", errors="replace") if resp_body else "(empty)"
        ]
        log_block(logger, "HTTP RESPONSE", resp_lines)

        # Append to session (CLI uses resolved URL here)
        append_request_to_session(folder, method, url, headers, body.decode("utf-8", errors="replace"))
        
        
        # NEW: apply per-request extractors (if any) tied to this item or method+URL
        apply_extractors_and_save(folder, item_path=None, method=method, template_url=url,
                                  status=status, headers=resp_headers, resp_body=resp_body, logger=logger)


        # NEW: Apply per-request extractors (CLI passes the same URL string as template)
        try:
            apply_extractors_for_request(
                folder=folder,
                method=method,
                template_url=url,
                status=status,
                headers=resp_headers,
                resp_body=resp_body,
                logger=logger,
                inline_rules=inline_rules or None
            )
        except Exception:
            pass

        # Schema validation
        _ = validate_and_log_schema(url, status, resp_headers, resp_body, folder, logger)

        # DIFF (pairwise)
        if compare_enabled and _is_json_content_type(resp_headers):
            ok, payload, perr = _safe_json_loads(resp_body)
            if ok:
                if pending_diff is None:
                    pending_diff = {"url": url, "status": status, "json": payload}
                    print("\n[Compare] Stored this response. Fire the next request to compare.")
                else:
                    diff = run_diff(pending_diff["json"], payload)
                    meta = {"url_a": pending_diff["url"], "status_a": pending_diff["status"],
                            "url_b": url, "status_b": status}
                    log_diff_block(logger, meta, diff)
                    if diff.get("valid"):
                        print("\n[Compare] ✅ No differences.")
                    else:
                        print(f"\n[Compare] ❌ Differences ({diff.get('count', 0)}):")
                        for line in diff.get("lines", []):
                            print(f" - {line}")
                    pending_diff = None
            else:
                print(f"\n[Compare] Skipped: response is not valid JSON ({perr}).")

        # Clear buffers
        resp_body = b""; body = b""

        print("\nWhat next?")
        print(" 1. Export all requests made in this session as a Postman collection and exit")
        print(" 2. Make another request")
        print(" 3. Exit without export")
        print(" C. Toggle Compare ON/OFF (currently: " + ("ON" if compare_enabled else "OFF") + ")")
        nxt = input("Choose 1/2/3/C: ").strip()
        if nxt == "1":
            name = input("Enter collection name (default 'Session Export'): ").strip() or "Session Export"
            out_path = export_session_jsonl_to_postman(folder, collection_name=name, delete_temp_vars=True)
            print(f"\nExported collection to: {out_path}")
            print(f"Logs written to: {log_file}")
            break
        elif nxt == "2":
            continue
        elif nxt == "3":
            print(f"\nExiting without export. Logs written to: {log_file}")
            break
        elif nxt.lower() == "c":
            compare_enabled = not compare_enabled
            pending_diff = None
            print(f"Compare is now {'ON' if compare_enabled else 'OFF'}.")
            continue
        else:
            print("Invalid choice; continuing to next request.")
            continue


def export_session_jsonl_to_postman(folder, collection_name="Export", delete_temp_vars=False):
    """
    Logic moved to export_utils.py to fix missing POST payloads 
    and keep api_engine clean.
    """
    folder = Path(folder)
    
    # Delegate the entire process to the new utility
    out_path = export_utils.handle_full_postman_export(
        folder, 
        collection_name, 
        session_jsonl_path(folder), 
        TEMP_VARS_FILENAME, 
        TempVarStore
    )

    # Clean up files as requested
    if delete_temp_vars:
        (folder / TEMP_VARS_FILENAME).unlink(missing_ok=True)
    session_jsonl_path(folder).unlink(missing_ok=True)

    return out_path


def main():
    ap = argparse.ArgumentParser(description="API engine (stdlib, RAM-safe, cURL import) with status-specific schema validation + optional diff + collection variables + per-request extractors.")
    ap.add_argument("--folder", type=Path, default=Path("."), help="Folder containing collection and where files are created")
    args = ap.parse_args()
    run_cli_interactive(args.folder)


if __name__ == "__main__":
    main()