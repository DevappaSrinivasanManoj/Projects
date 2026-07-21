#!/usr/bin/env python3
"""
pm_runtime.py
-------------
Postman-compatible 'pm' object for script execution.

Provides:
- pm.response.json()       -> DotDict (supports .data.user.id style)
- pm.response.headers      -> DotDict of response headers
- pm.response.status       -> int status code
- pm.response.text         -> raw response body text
- pm.collectionVariables.set(key, value)
- pm.collectionVariables.get(key)
- pm.request.url           -> request URL (mutable in pre-request)
- pm.request.headers       -> dict of request headers (mutable)
- pm.request.body          -> request body text (mutable)
- pm.request.method        -> HTTP method (mutable)
"""

import json
from typing import Any, Dict, Optional


class DotDict(dict):
    """Dict subclass that allows attribute-style access for keys.
    
    Enables pm.response.json().data.user.id syntax just like Postman JS.
    Falls back to regular dict behavior for non-existent attributes.
    """

    def __getattr__(self, key: str) -> Any:
        try:
            value = self[key]
        except KeyError:
            raise AttributeError(f"No such key: '{key}'")
        # Wrap and store back so mutations persist
        wrapped = _wrap(value)
        if wrapped is not value:
            self[key] = wrapped
        return wrapped

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value

    def __delattr__(self, key: str) -> None:
        try:
            del self[key]
        except KeyError:
            raise AttributeError(f"No such key: '{key}'")


def _wrap(obj: Any) -> Any:
    """Recursively wrap dicts/lists IN-PLACE so dot-access and mutations work at any depth."""
    if isinstance(obj, dict) and not isinstance(obj, DotDict):
        d = DotDict(obj)
        # Wrap nested values in-place
        for k, v in list(d.items()):
            wrapped = _wrap(v)
            if wrapped is not v:
                d[k] = wrapped
        return d
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            wrapped = _wrap(item)
            if wrapped is not item:
                obj[i] = wrapped
        return obj
    return obj


class _CollectionVariables:
    """Mimics pm.collectionVariables in Postman."""

    def __init__(self, var_store):
        self._store = var_store

    def set(self, key: str, value: Any) -> None:
        self._store.set(str(key), "" if value is None else str(value))
        self._store.save()

    def get(self, key: str) -> str:
        self._store.load()
        return self._store.get(str(key), "")

    def unset(self, key: str) -> None:
        self._store.delete(str(key))
        self._store.save()

    def has(self, key: str) -> bool:
        self._store.load()
        return str(key) in self._store.data


class _Response:
    """Mimics pm.response in Postman."""

    def __init__(self, status: int = 0, headers: Optional[Dict[str, str]] = None,
                 body_text: str = ""):
        self.status = status
        self.headers = DotDict(headers or {})
        self._body_text = body_text
        self._json_cache = None

    def json(self) -> Any:
        if self._json_cache is None:
            self._json_cache = _wrap(json.loads(self._body_text))
        return self._json_cache

    @property
    def text(self) -> str:
        return self._body_text

    @property
    def code(self) -> int:
        return self.status


class _Request:
    """Mimics pm.request in Postman (mutable for pre-request scripts)."""

    def __init__(self, method: str = "GET", url: str = "",
                 headers: Optional[Dict[str, str]] = None, body: str = ""):
        self.method = method
        self.url = url
        self.headers = dict(headers or {})
        self.body = body


class PmContext:
    """The top-level 'pm' object available in scripts."""

    def __init__(self, var_store, response: Optional[_Response] = None,
                 request: Optional[_Request] = None):
        self.collectionVariables = _CollectionVariables(var_store)
        self.response = response or _Response()
        self.request = request or _Request()

    # Convenience aliases matching Postman
    @property
    def variables(self):
        return self.collectionVariables


def build_pm_context(var_store, status: int = 0, resp_headers: Optional[Dict[str, str]] = None,
                     resp_body: str = "", method: str = "GET", url: str = "",
                     req_headers: Optional[Dict[str, str]] = None,
                     req_body: str = "") -> PmContext:
    """Factory to create a fully wired pm context for script execution."""
    response = _Response(status=status, headers=resp_headers, body_text=resp_body)
    request = _Request(method=method, url=url, headers=req_headers, body=req_body)
    return PmContext(var_store=var_store, response=response, request=request)


def run_script(script: str, pm: PmContext):
    """Execute a script string with 'pm' in scope.
    
    Returns a tuple: (error_or_none, captured_stdout)
    - error: None on success, or an error message string on failure.
    - captured_stdout: string of any print() output from the script.
    """
    if not script or not script.strip():
        return None, ""

    # Provide common imports in the script scope for convenience
    import base64
    import hashlib
    import time
    import re as re_mod
    import sys
    from io import StringIO

    scope = {
        "pm": pm,
        "base64": base64,
        "hashlib": hashlib,
        "time": time,
        "re": re_mod,
        "json": json,
        "__builtins__": __builtins__,
        "__file__": __file__,  # allows scripts to anchor paths relative to src/
    }

    # Capture stdout
    old_stdout = sys.stdout
    sys.stdout = captured = StringIO()

    try:
        exec(script, scope)
        return None, captured.getvalue()
    except SyntaxError as e:
        return f"Script error: {type(e).__name__}: {e}\n— This may be a JS script that needs a Python equivalent.", captured.getvalue()
    except Exception as e:
        return f"Script error: {type(e).__name__}: {e}", captured.getvalue()
    finally:
        sys.stdout = old_stdout
