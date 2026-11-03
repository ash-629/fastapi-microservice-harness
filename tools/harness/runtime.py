# 覆盖 H02：仅管理当前项目启动的进程。
import json
import os
import subprocess
import sys
import time

import httpx

from .cli import ROOT


def dispatch(args):
    state = ROOT / ".runtime"
    state.mkdir(exist_ok=True)
    if args.command == "up":
        if (state / "processes.json").exists():
            raise RuntimeError("Runtime record exists; run down first")
        children = []
        try:
            for name, port in [("inventory", 8002), ("orders", 8001)]:
                import socket

                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", port))
                env = dict(os.environ, DB_PATH=str(state / f"{name}.sqlite3"))
                log = open(state / f"{name}.log", "a")
                p = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        f"{'inventory_service' if name == 'inventory' else 'order_service'}.main:create_app",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=log,
                    stderr=log,
                    creationflags=0x08000000 if os.name == "nt" else 0,
                )
                log.close()
                children.append(p)
                for _ in range(60):
                    try:
                        if httpx.get(f"http://127.0.0.1:{port}/health/ready").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.2)
                else:
                    raise RuntimeError(f"{name} failed; inspect .runtime logs")
            import shutil

            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 5173))
            node = shutil.which("node")
            if node is None:
                raise RuntimeError("Node.js not found")
            with open(state / "web.log", "a") as web_log:
                web = subprocess.Popen(
                    [
                        node,
                        str(ROOT / "web/node_modules/vite/bin/vite.js"),
                        "--host",
                        "127.0.0.1",
                        "--port",
                        "5173",
                        "--strictPort",
                    ],
                    cwd=ROOT / "web",
                    stdout=web_log,
                    stderr=web_log,
                    creationflags=0x08000000 if os.name == "nt" else 0,
                )
            children.append(web)
            for _ in range(60):
                try:
                    if httpx.get("http://127.0.0.1:5173").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("frontend not ready")
            # psutil creation timestamp prevents stale PID reuse.
            import psutil

            records = [
                {
                    "pid": p.pid,
                    "created": psutil.Process(p.pid).create_time(),
                    "cmdline": psutil.Process(p.pid).cmdline(),
                }
                for p in children
            ]
            (state / "processes.json").write_text(json.dumps(records))
            print("Ready: http://127.0.0.1:5173 ; API docs: 8001/docs and 8002/docs")
        except BaseException:
            for p in children:
                p.terminate()
                p.wait(timeout=10)
            raise
    elif args.command == "down":
        import psutil

        f = state / "processes.json"
        if f.exists():
            for item in json.loads(f.read_text()):
                try:
                    process = psutil.Process(item["pid"])
                    if (
                        abs(process.create_time() - item["created"]) < 0.01
                        and process.cmdline() == item["cmdline"]
                    ):
                        process.terminate()
                        process.wait(5)
                except psutil.NoSuchProcess:
                    pass
            f.unlink()
    elif args.command == "smoke":
        for port in [8001, 8002]:
            response = httpx.get(f"http://127.0.0.1:{port}/health/ready")
            response.raise_for_status()
        print("Read-only readiness PASS; full tests cover isolated business flow")
    elif args.command == "reconcile":
        from order_service.service import reconcile

        if not args.order_id:
            raise ValueError("--order-id required")
        print(reconcile(str(state / "orders.sqlite3"), "http://127.0.0.1:8002", args.order_id))
    elif args.command == "seed":
        from inventory_service.service import init

        init(str(state / "inventory.sqlite3"))
        print("Missing seed products inserted; existing stock preserved")
