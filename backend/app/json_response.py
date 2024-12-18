"""JSON response class that guarantees RFC-compliant output.

FastAPI/Starlette serialize with ``allow_nan=False``, so any stray
``float('nan')`` (e.g. from a degenerate statistical computation on an
empty slice) would otherwise produce a 500 error. This response class
recursively converts non-finite floats to ``None`` so the API degrades
gracefully and surfaces "metric undefined" instead of crashing.
"""

from __future__ import annotations

import math
from typing import Any

from fastapi.responses import JSONResponse


def _sanitize(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_sanitize(v) for v in value]
    return value


class SafeJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return super().render(_sanitize(content))
