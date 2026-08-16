from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import platform
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the optional Orbbec SDK v2 Python binding for task2")
    parser.add_argument("--allow-missing", action="store_true", help="return success when the SDK is absent")
    args = parser.parse_args()

    payload = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "distribution": "pyorbbecsdk2",
        "module": "pyorbbecsdk",
        "installed": False,
        "version": None,
        "error": None,
    }
    try:
        module = importlib.import_module("pyorbbecsdk")
        payload["installed"] = True
        payload["version"] = getattr(module, "__version__", None)
        if payload["version"] is None:
            try:
                payload["version"] = importlib.metadata.version("pyorbbecsdk2")
            except importlib.metadata.PackageNotFoundError:
                payload["version"] = "unknown"
    except Exception as error:
        payload["error"] = f"{type(error).__name__}: {error}"

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["installed"] or args.allow_missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
