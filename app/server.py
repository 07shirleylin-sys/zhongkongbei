from __future__ import annotations

import argparse
import json
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from app.context import RuntimeContext, build_context
from tasks.task1_switch import run_task1
from tasks.task2_blocks import run_task2
from tasks.task3_shapes import run_task3


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "local.json"
MAX_REQUEST_BODY_SIZE = 1024 * 1024


TaskRunner = Callable[[RuntimeContext], tuple[bool, str]]


TASK_ROUTES: dict[str, TaskRunner] = {
    "/api/task1/execute": run_task1,
    "/api/task2/execute": run_task2,
    "/api/task3/execute": run_task3,
}


class ContestantAlgorithmServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], context: RuntimeContext) -> None:
        super().__init__(server_address, ContestantRequestHandler)
        self.context = context


class ContestantRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ZhongkongbeiAlgorithm/0.1"

    @property
    def algorithm_server(self) -> ContestantAlgorithmServer:
        return self.server  # type: ignore[return-value]

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/health":
            self._send_json(HTTPStatus.OK, {"success": True, "message": "ready"})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"success": False, "message": f"unknown path: {self.path}"})

    def do_POST(self) -> None:  # noqa: N802
        runner = TASK_ROUTES.get(self.path)
        if runner is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"success": False, "message": f"unknown path: {self.path}"})
            return

        if self._read_json_request() is None:
            return

        started_at = time.perf_counter()
        try:
            ok, message = runner(self.algorithm_server.context)
        except Exception as error:
            traceback.print_exc()
            ok, message = False, f"{type(error).__name__}: {error}"

        elapsed_ms = round((time.perf_counter() - started_at) * 1000)
        self._send_json(
            HTTPStatus.OK,
            {"success": bool(ok), "message": message, "elapsedMs": elapsed_ms},
        )

    def _read_json_request(self) -> dict[str, Any] | None:
        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("application/json"):
            self._send_json(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                {"success": False, "message": "Content-Type must be application/json"},
            )
            return None

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"success": False, "message": "invalid Content-Length"})
            return None

        if content_length > MAX_REQUEST_BODY_SIZE:
            self._send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"success": False, "message": "request body too large"})
            return None

        raw_body = self.rfile.read(content_length)
        try:
            body = json.loads(raw_body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"success": False, "message": "request body must be UTF-8 JSON"})
            return None

        if not isinstance(body, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"success": False, "message": "request JSON root must be an object"})
            return None

        print(f"[request] {self.command} {self.path} body={body}", flush=True)
        return body

    def _send_json(self, status: int | HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

    def log_message(self, format_text: str, *args: object) -> None:
        del format_text, args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="中控杯选手算法统一服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址；现场建议 0.0.0.0")
    parser.add_argument("--port", type=int, default=5000, help="选手算法服务端口")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    context = build_context(args.config)
    server = ContestantAlgorithmServer((args.host, args.port), context)
    print("=" * 64)
    print("中控杯选手算法统一服务已启动")
    print(f"Base URL: http://{args.host}:{args.port}")
    print("Contest endpoints:")
    print("  GET  /api/health")
    print("  POST /api/task1/execute")
    print("  POST /api/task2/execute")
    print("  POST /api/task3/execute")
    print(f"Config: {args.config}")
    print("=" * 64, flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\n正在停止服务...", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
