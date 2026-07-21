#!/usr/bin/env python3
"""
temp_var_store.py
-----------------
Crash-resilient, per-folder variable store for Postman-style {{var}} placeholders.

Behavior:
- Keeps variables in memory; persists to a temp file for resilience:
    ./temp.collection.vars.json
- Designed to be used by both CLI (api_engine.py) and GUI (gui_app.py).
- Deleted automatically by api_engine.export_session_jsonl_to_postman(...) after a
  successful export (per your requirement).

APIs:
- TempVarStore(path)
    .load(), .save()
    .get(key, default=""), .set(key, value), .delete(key)
    .keys(), .items(), .clear()
    .render_text(s: str) -> str
    .render_headers(headers: dict) -> dict
    .to_postman_variables() -> list[{key,value,type}]
"""

import json
import re
import uuid
import time
import random
from pathlib import Path
from typing import Dict, Any, Iterable

TEMP_VARS_FILENAME = "temp.collection.vars.json"

# Postman-style {{var}} and {{$dynamicVar}} placeholders
_VAR_RE = re.compile(r"\{\{\s*(\$?[A-Za-z0-9_.\-]+)\s*\}\}")

# Dynamic variable generators (Postman-compatible)
# Each call produces a fresh value — never cached.
_DYNAMIC_VARS = {
    "$randomUUID": lambda: str(uuid.uuid4()),
    "$guid":       lambda: str(uuid.uuid4()),
    "$timestamp":  lambda: str(int(time.time())),
    "$randomInt":  lambda: str(random.randint(0, 1000)),
}

class TempVarStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: Dict[str, str] = {}
        self.load()

    # ---- Persistence ---------------------------------------------------------
    def load(self) -> None:
        try:
            if self.path.exists():
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(self.data, dict):
                    self.data = {}
        except Exception:
            self.data = {}

    def save(self) -> None:
        try:
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except Exception:
            pass  # best-effort; caller may retry

    # ---- Basic ops -----------------------------------------------------------
    def get(self, key: str, default: str = "") -> str:
        return str(self.data.get(str(key), default))

    def set(self, key: str, value: Any) -> None:
        self.data[str(key)] = "" if value is None else str(value)

    def delete(self, key: str) -> None:
        try:
            del self.data[str(key)]
        except KeyError:
            pass

    def keys(self) -> Iterable[str]:
        return self.data.keys()

    def items(self) -> Iterable:
        return self.data.items()

    def clear(self) -> None:
        self.data.clear()

    # ---- Rendering -----------------------------------------------------------
    def render_text(self, s: str) -> str:
        if not s:
            return s
        # Reload to pick up updates saved by the GUI right before send.
        self.load()
        def repl(m):
            k = m.group(1)
            # Dynamic variables — generated fresh on every substitution
            gen = _DYNAMIC_VARS.get(k)
            if gen is not None:
                return gen()
            return self.get(k, "")
        return _VAR_RE.sub(repl, s)

    def render_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        if not headers:
            return {}
        self.load()
        out = {}
        for k, v in headers.items():
            # Most people template header values, not keys. Keep keys as-is.
            out[k] = self.render_text(str(v))
        return out

    # ---- Postman collection integration -------------------------------------
    def to_postman_variables(self):
        # Convert to Postman v2.1 "variable" array
        arr = []
        for k, v in self.data.items():
            arr.append({"key": str(k), "value": str(v), "type": "string"})
        return arr