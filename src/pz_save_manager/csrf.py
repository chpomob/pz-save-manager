"""CSRF token helpers for the Flask GUI."""

from __future__ import annotations

import secrets
from typing import Any

from flask import jsonify, request

CSRF_TOKEN: str = secrets.token_hex(32)


def _generate_csrf_token() -> str:
    """Return the process-local CSRF token used by the GUI."""
    return CSRF_TOKEN


def _check_csrf() -> Any | None:
    """Return a Flask error response when the request CSRF token is invalid."""
    token = request.headers.get("X-CSRF-Token", "")
    if not secrets.compare_digest(token, CSRF_TOKEN):
        return jsonify({"ok": False, "error": "Invalid CSRF token"}), 403
    return None


def _validate_csrf() -> Any | None:
    """Backward-compatible alias for callers that use validate terminology."""
    return _check_csrf()
