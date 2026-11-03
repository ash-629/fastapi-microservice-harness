import importlib.metadata
import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path


def diagnose(root: Path) -> dict:
    missing: list[str] = []
    tools = {
        name: shutil.which(name)
        for name in ["node", "npm.cmd" if sys.platform == "win32" else "npm", "git"]
    }
    missing.extend(name for name, path in tools.items() if path is None)
    version = None
    if tools["node"]:
        result = subprocess.run(
            [tools["node"], "--version"], text=True, capture_output=True, check=True
        )
        version = result.stdout.strip()
        parts = version.lstrip("v").split(".")
        major, minor = map(int, parts[:2])
        if not ((major == 20 and minor >= 19) or (major == 22 and minor >= 12) or major > 22):
            missing.append("Node.js must satisfy ^20.19.0 || >=22.12.0")
    for name in [
        "uv.lock",
        "web/package-lock.json",
        "contracts/orders.openapi.json",
        "contracts/inventory.openapi.json",
    ]:
        if not (root / name).exists():
            missing.append(name)
    packages = {}
    for name in [
        "fastapi",
        "pydantic",
        "pytest",
        "ruff",
        "mypy",
        "orders-service",
        "inventory-service",
    ]:
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(name)
    ports = {}
    for port in [8001, 8002, 5173]:
        with socket.socket() as sock:
            ports[str(port)] = (
                "in use" if sock.connect_ex(("127.0.0.1", port)) == 0 else "available"
            )
    hooks = root / ".codex/hooks.json"
    try:
        json.loads(hooks.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        missing.append("valid .codex/hooks.json")
    return {
        "status": "FAIL" if missing else "PASS",
        "python": sys.version,
        "node": version,
        "tools": tools,
        "packages": packages,
        "ports": ports,
        "missing": missing,
        "git_repository": (root / ".git").exists(),
        "native_hooks": "configuration checked; client trust and real event dispatch require target-client validation",
    }
