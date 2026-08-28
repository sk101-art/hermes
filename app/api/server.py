import argparse
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.api.routes import router
from app.runtime.state import load_runtime_config

app = FastAPI(
    title="HERMES Intelligence API",
    description="Local read-only API for HERMES Personal Technology Intelligence",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    # Loopback origins only: the built UI is served same-origin, and the Vite
    # dev server runs on 127.0.0.1/localhost. Any other origin (e.g. a
    # malicious webpage) is denied CORS, so it cannot call the sensitive
    # /local/* endpoints from browser code.
    allow_origin_regex=r"https?://(127\.0\.0\.1|localhost)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Serve the built frontend (frontend/dist) from the API server itself so the
# entire product lives at a single URL (http://127.0.0.1:8765) with no
# separate web server to manage. The SPA uses hash-based routing, so it only
# needs the index document at "/" plus the hashed build assets under /assets.
#
# We deliberately do NOT mount StaticFiles at "/" — a root mount would
# intercept every path and return 405 for POST/PUT/DELETE to removed API
# endpoints instead of the truthful 404 the API contract requires. Instead:
#   - "/"            -> serves index.html explicitly
#   - "/assets/*"    -> serves the hashed build assets
# API routes are registered first, so they always take precedence, and any
# unknown API path still falls through to the router's 404 handling.
FRONTEND_DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if FRONTEND_DIST_DIR.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST_DIR / "assets")),
        name="frontend-assets",
    )

    @app.get("/", include_in_schema=False)
    def serve_frontend_index():
        return FileResponse(str(FRONTEND_DIST_DIR / "index.html"))


def validate_api_host(host: str, allow_external: bool = False) -> str:
    """Validates listen address to prevent accidental external network exposure."""
    safe_local_hosts = {"127.0.0.1", "localhost", "::1"}
    if host not in safe_local_hosts and not allow_external:
        print(f"[SECURITY WARNING] Non-local API host '{host}' detected without explicit allow_external flag.")
        print("[SECURITY] Binding to safe local default: 127.0.0.1")
        return "127.0.0.1"
    return host


def main():
    parser = argparse.ArgumentParser(description="HERMES — Local Read API Server")
    parser.add_argument("--host", type=str, default=None, help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Port to bind (default: 8765)")
    parser.add_argument("--allow-external", action="store_true", help="Allow binding to non-localhost address")
    args = parser.parse_args()

    config = load_runtime_config()
    api_cfg = config.get("api", {})

    host = args.host or api_cfg.get("host", "127.0.0.1")
    port = args.port or api_cfg.get("port", 8765)
    allow_external = args.allow_external or api_cfg.get("allow_external", False)

    safe_host = validate_api_host(host, allow_external=allow_external)

    # Sensitive local-machine endpoints (native folder picker, approvals) are
    # disabled entirely when the API is externally exposed.
    from app.api.security import set_external_exposure
    set_external_exposure(safe_host not in {"127.0.0.1", "localhost", "::1"})

    print("=" * 70)
    print("HERMES — LOCAL TECHNOLOGY INTELLIGENCE API")
    print("=" * 70)
    print(f"Host:       {safe_host}")
    print(f"Port:       {port}")
    if FRONTEND_DIST_DIR.is_dir():
        print(f"UI:         http://{safe_host}:{port}/  (built frontend served here)")
    else:
        print(f"UI:         frontend/dist not built — run 'npm run build' in frontend/")
    print(f"Swagger:    http://{safe_host}:{port}/docs")
    print(f"Endpoints:  /health, /search, /inbox, /stories, /claims, /projects, /saved")
    print("=" * 70)

    uvicorn.run(app, host=safe_host, port=port, log_level="info")


if __name__ == "__main__":
    main()
