import argparse
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


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

    print("=" * 70)
    print("HERMES — LOCAL TECHNOLOGY INTELLIGENCE API")
    print("=" * 70)
    print(f"Host:       {safe_host}")
    print(f"Port:       {port}")
    print(f"Swagger:    http://{safe_host}:{port}/docs")
    print(f"Endpoints:  /health, /search, /inbox, /stories, /claims, /projects, /saved")
    print("=" * 70)

    uvicorn.run(app, host=safe_host, port=port, log_level="info")


if __name__ == "__main__":
    main()
