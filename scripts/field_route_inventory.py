#!/usr/bin/env python3
"""Inventory compiled Crow registrations and live FastAPI app.routes, not OpenAPI."""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python_service"))


def inventory() -> dict:
    from fastapi import FastAPI
    from fastapi.routing import APIRoute
    from starlette.routing import WebSocketRoute
    from httpserver.main import _register_routes
    from httpserver.services.field_security import required_permission

    def protection(method, path):
        if path == "/health/live":
            return "ANONYMOUS_MINIMAL_LIVE"
        if path == "/api/field-auth/login" and method == "POST":
            return "ANONYMOUS_CREDENTIAL_CHECK"
        if path == "/api/field-auth/introspect":
            return "SERVICE_ONLY_CPP_TO_PYTHON"
        return required_permission(method, path)

    app = FastAPI()
    _register_routes(app)
    # FastAPI's current include_router implementation keeps lazy
    # _IncludedRouter entries. Walk their *registered* child routes and
    # prefixes rather than treating an empty app.routes APIRoute filter as
    # evidence of no protected endpoints.
    def effective_routes(routes, prefix=""):
        for route in routes:
            if isinstance(route, APIRoute):
                yield prefix + route.path, route.methods
            elif isinstance(route, WebSocketRoute):
                yield prefix + route.path, {"WEBSOCKET"}
            elif hasattr(route, "original_router") and hasattr(route, "include_context"):
                yield from effective_routes(route.original_router.routes,
                                            prefix + route.include_context.prefix)

    python = [{"method": method, "path": path,
               "permission": protection(method, path)}
              for path, methods in effective_routes(app.routes)
              for method in sorted(methods - {"OPTIONS"})]
    cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
    source_names = sorted(set(re.findall(r"src/network/HTTPServer/(?:routes/)?[\w]+\.cpp", cmake)))
    cpp = []
    pattern = re.compile(r'CROW_ROUTE\s*\(\s*app_?\s*,\s*"([^\"]+)"\s*\)(.{0,220})', re.S)
    for name in source_names:
        source = (ROOT / name).read_text(encoding="utf-8", errors="replace")
        for route in pattern.finditer(source):
            declaration = route.group(2)
            method_match = re.search(r"\.methods\s*\(([^)]*)\)", declaration)
            methods = re.findall(r'"([A-Z]+)"_method', method_match.group(1)) if method_match else ["GET"]
            for method in methods:
                if method == "OPTIONS":
                    continue
                cpp.append({"method": method, "path": route.group(1), "source": name,
                            "permission": protection(method, route.group(1))})
    return {"schema": "field-route-inventory-v1",
            "source": "FastAPI app.routes + CMake-compiled CROW_ROUTE declarations",
            "global_guard": "C++ FieldAuthMiddleware and Python field_authentication; unknown /api paths are guarded",
            "anonymous_exceptions": ["GET /health/live (C++ and Python): minimal alive only",
                                     "POST /api/field-auth/login (Python): credential check",
                                     "OPTIONS: CORS preflight only, no data body", "GET static SPA assets (C++): confined to web/dist"],
            "service_only": ["POST /api/field-auth/introspect (Python): loopback + C++ service token"],
            "python": sorted(python, key=lambda item: (item["path"], item["method"])),
            "cpp": sorted(cpp, key=lambda item: (item["path"], item["method"])),
            "cpp_websocket_route_count": sum((ROOT / name).read_text(encoding="utf-8", errors="replace").count("CROW_WEBSOCKET_ROUTE")
                                             for name in source_names)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(inventory(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
        print(f"route inventory generated: {args.output}")
    else:
        print(payload, end="")
