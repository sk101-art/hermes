import json
import os
import sys
from pathlib import Path


def generate_mcp_config() -> dict:
    """Generates dynamic local MCP server configuration snippet."""
    repo_root = str(Path(__file__).parent.parent.parent.resolve())
    python_exe = sys.executable

    config = {
        "mcpServers": {
            "hermes": {
                "command": python_exe,
                "args": ["-m", "app.mcp.server"],
                "cwd": repo_root,
                "env": {
                    "PYTHONUNBUFFERED": "1"
                }
            }
        }
    }
    return config


def main():
    config = generate_mcp_config()
    print("=" * 70)
    print("HERMES — MCP SERVER CLIENT CONFIGURATION")
    print("=" * 70)
    print("Add the following configuration to your MCP client:")
    print("(e.g., Claude Desktop: %APPDATA%/Claude/claude_desktop_config.json)")
    print("=" * 70)
    print(json.dumps(config, indent=2))
    print("=" * 70)


if __name__ == "__main__":
    main()
