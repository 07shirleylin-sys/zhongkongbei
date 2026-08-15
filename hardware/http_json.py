from __future__ import annotations

import json
from urllib import request


def get_json(base_url: str, path: str, timeout: float = 5) -> dict:
    with request.urlopen(base_url.rstrip("/") + path, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(base_url: str, path: str, payload: dict | None = None, timeout: float = 30) -> dict:
    body = json.dumps(payload or {}).encode("utf-8")
    req = request.Request(
        base_url.rstrip("/") + path,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))
