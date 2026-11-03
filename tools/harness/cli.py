# 跨入口复用检查、离线契约与内容证据。
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import shutil
import importlib.metadata
from uuid import uuid4
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(args, cwd=ROOT):
    subprocess.run(args, cwd=cwd, check=True, shell=False)


def fingerprint():
    h = hashlib.sha256()
    from .packaging import source_files

    versions = {
        name: importlib.metadata.version(name)
        for name in ["fastapi", "pydantic", "ruff", "mypy", "pytest"]
    }
    h.update(json.dumps({"python": sys.version, "packages": versions}, sort_keys=True).encode())
    for p in sorted(source_files(ROOT)):
        if (
            p.suffix == ".log"
            or not p.is_file()
            or any(
                x in p.parts
                for x in [
                    ".git",
                    ".vite",
                    ".venv",
                    "node_modules",
                    ".runtime",
                    ".harness",
                    "__pycache__",
                    ".pytest_cache",
                    ".ruff_cache",
                    ".mypy_cache",
                    "dist",
                    "test-results",
                    "playwright-report",
                ]
            )
        ):
            continue
        h.update(p.relative_to(ROOT).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def contract(generate=False):
    from inventory_service.main import create_app as inventory
    from order_service.main import create_app as orders

    for name, factory in [("orders", orders), ("inventory", inventory)]:
        data = json.dumps(factory().openapi(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        p = ROOT / "contracts" / f"{name}.openapi.json"
        if generate:
            p.parent.mkdir(exist_ok=True)
            p.write_text(data, encoding="utf-8")
        elif not p.exists() or p.read_text(encoding="utf-8") != data:
            raise RuntimeError(f"{name} contract drift: run harness contract generate")
    npm = "npm.cmd" if os.name == "nt" else "npm"
    if generate:
        run([npm, "run", "generate"], ROOT / "web")
    else:
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "generated"
            dependency_root = Path(os.environ.get("HARNESS_DEPENDENCY_ROOT", str(ROOT)))
            node = shutil.which("node")
            generator = dependency_root / "web/node_modules/@hey-api/openapi-ts/bin/run.js"
            if not node or not generator.exists():
                raise RuntimeError("Run npm ci in web before contract checks")
            for name in ["orders", "inventory"]:
                run(
                    [
                        node,
                        str(generator),
                        "-c",
                        "@hey-api/client-fetch",
                        "-i",
                        str(ROOT / "contracts" / f"{name}.openapi.json"),
                        "-o",
                        str(out / name),
                    ],
                    ROOT / "web",
                )
            generated = {p.relative_to(out) for p in out.rglob("*") if p.is_file()}
            committed = {
                p.relative_to(ROOT / "web/src/api/generated")
                for p in (ROOT / "web/src/api/generated").rglob("*")
                if p.is_file()
            }
            if not generated or generated != committed:
                raise RuntimeError(
                    "generated client file set differs or generator produced no files"
                )
            for p in out.rglob("*"):
                if p.is_file():
                    target = ROOT / "web/src/api/generated" / p.relative_to(out)
                    if not target.exists() or target.read_text(encoding="utf-8") != p.read_text(
                        encoding="utf-8"
                    ):
                        raise RuntimeError("generated client drift: " + str(p.relative_to(out)))


def architecture():
    import ast

    for service, forbidden in [("orders", "inventory_service"), ("inventory", "order_service")]:
        for p in (ROOT / "services" / service / "src").rglob("*.py"):
            tree = ast.parse(p.read_text(encoding="utf-8"))
            for n in ast.walk(tree):
                names = (
                    [x.name for x in n.names]
                    if isinstance(n, ast.Import)
                    else [n.module or ""]
                    if isinstance(n, ast.ImportFrom)
                    else []
                )
                if any(x.startswith(forbidden) for x in names):
                    raise RuntimeError(f"cross-service import: {p}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "doctor",
            "check",
            "contract",
            "report",
            "smoke",
            "up",
            "down",
            "reconcile",
            "seed",
            "hooks",
            "task",
            "staged",
            "package",
        ],
    )
    parser.add_argument("action", nargs="?")
    parser.add_argument("--scope", choices=["quick", "affected", "full"], default="affected")
    parser.add_argument("--order-id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--isolated", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.command == "staged":
        from .staged import check_staged

        check_staged()
        return
    if args.command == "package":
        from .packaging import package

        if not args.output:
            raise ValueError("--output required")
        print(package(ROOT, args.output))
        return
    if args.command == "task":
        from .hooks import read_json, verified

        path = ROOT / ".harness/task.json"
        path.parent.mkdir(exist_ok=True)
        if args.action == "start":
            path.write_text(
                json.dumps({"active": True, "scope": args.scope, "dirty": True}), encoding="utf-8"
            )
            print(f"Code task started; required checks: {args.scope}")
        elif args.action == "finish":
            task = read_json(path)
            if not verified(
                read_json(ROOT / ".harness/latest.json"),
                task.get("scope", "affected"),
                fingerprint(),
            ):
                raise RuntimeError("No valid verification for current task")
            task["active"] = False
            path.write_text(json.dumps(task), encoding="utf-8")
            print("Task verified and finished")
        else:
            raise ValueError("use task start or task finish")
        return
    if args.command == "hooks":
        if args.action != "install":
            raise ValueError("use hooks install")
        for hook in (ROOT / ".githooks").iterdir():
            hook.chmod(hook.stat().st_mode | 0o111)
        run(["git", "config", "--local", "core.hooksPath", ".githooks"])
        print("Git hooks installed. AI hooks require target-client trust; not auto-enabled.")
        return
    if args.command == "smoke" and args.isolated:
        run([sys.executable, "-m", "pytest", "-q", "tests/test_integration.py"])
        return
    if args.command == "doctor":
        from .doctor import diagnose

        result = diagnose(ROOT)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["status"] == "PASS" else 1)
    if args.command == "contract":
        contract(args.action == "generate")
        return
    if args.command == "report":
        p = ROOT / ".harness/latest.json"
        if p.exists():
            receipt = json.loads(p.read_text())
            receipt["current"] = receipt.get("fingerprint") == fingerprint()
            print(json.dumps(receipt, indent=2))
        else:
            print("No verification receipt")
        return
    if args.command == "check":
        started = time.perf_counter()
        run_id = str(uuid4())
        start_fingerprint = fingerprint()
        results = []
        try:
            uv = shutil.which("uv")
            run(
                ([uv] if uv else [getattr(sys, "_base_executable", sys.executable), "-m", "uv"])
                + ["lock", "--check"]
            )
            results.append({"name": "dependency-lock", "status": "PASS"})
            for label, cmd in [
                ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
                ("format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
            ]:
                run(cmd)
                results.append({"name": label, "status": "PASS"})
            from .documentation import check as check_documentation

            check_documentation(ROOT)
            results.append({"name": "documentation", "status": "PASS"})
            architecture()
            results.append({"name": "architecture", "status": "PASS"})
            contract()
            results.append({"name": "contract", "status": "PASS"})
            run(
                [
                    sys.executable,
                    "-m",
                    "mypy",
                    "services/orders/src",
                    "services/inventory/src",
                    "tools",
                ]
            )
            results.append({"name": "mypy", "status": "PASS"})
            if args.scope != "quick":
                run([sys.executable, "-m", "pytest", "-q"])
                results.append({"name": "pytest", "status": "PASS"})
            run(["npm.cmd" if os.name == "nt" else "npm", "run", "build"], ROOT / "web")
            results.append({"name": "frontend-build", "status": "PASS"})
            run(["npm.cmd" if os.name == "nt" else "npm", "run", "format:check"], ROOT / "web")
            results.append({"name": "frontend-format", "status": "PASS"})
            if args.scope == "full":
                os.environ["HARNESS_PYTHON"] = sys.executable
                with tempfile.TemporaryDirectory(prefix="harness-browser-") as browser_data:
                    os.environ["HARNESS_BROWSER_DATA_DIR"] = browser_data
                    try:
                        run(
                            [
                                "npm.cmd" if os.name == "nt" else "npm",
                                "exec",
                                "--",
                                "playwright",
                                "test",
                            ],
                            ROOT / "web",
                        )
                    finally:
                        os.environ.pop("HARNESS_BROWSER_DATA_DIR", None)
                results.append({"name": "playwright", "status": "PASS"})
        except Exception as exc:
            results.append({"name": "failure", "status": "FAIL", "message": str(exc)})
        if fingerprint() != start_fingerprint:
            results.append(
                {
                    "name": "concurrent-edit",
                    "status": "FAIL",
                    "message": "Source changed during verification",
                }
            )
        receipt = {
            "run_id": run_id,
            "duration_seconds": round(time.perf_counter() - started, 2),
            "scope": args.scope,
            "status": "FAIL" if any(x["status"] == "FAIL" for x in results) else "PASS",
            "fingerprint": fingerprint(),
            "checks": results,
        }
        p = ROOT / ".harness/latest.json"
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        history = ROOT / ".harness/runs"
        history.mkdir(exist_ok=True)
        (history / (run_id + ".json")).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(json.dumps(receipt, indent=2))
        sys.exit(receipt["status"] != "PASS")
    from .runtime import dispatch

    dispatch(args)


if __name__ == "__main__":
    main()
