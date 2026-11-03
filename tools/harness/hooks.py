"""显式代码任务的生命周期反馈；不启动服务或安装依赖。"""

import json
import sys
from pathlib import Path

from . import cli

BASE_CHECKS = {
    "dependency-lock",
    "documentation",
    "ruff",
    "format",
    "architecture",
    "contract",
    "mypy",
    "frontend-build",
    "frontend-format",
}
REQUIRED = {
    "quick": BASE_CHECKS,
    "affected": BASE_CHECKS | {"pytest"},
    "full": BASE_CHECKS | {"pytest", "playwright"},
}


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def verified(receipt: dict, scope: str, current: str) -> bool:
    checks = receipt.get("checks", [])
    if not isinstance(checks, list):
        return False
    passed = {c.get("name") for c in checks if isinstance(c, dict) and c.get("status") == "PASS"}
    return (
        receipt.get("status") == "PASS"
        and receipt.get("fingerprint") == current
        and REQUIRED[scope].issubset(passed)
        and all(isinstance(c, dict) and c.get("status") == "PASS" for c in checks)
    )


def handle(event: str, data: dict, root: Path = cli.ROOT) -> dict:
    if event == "SessionStart":
        return {
            "systemMessage": "入口 AGENTS.md；开发指南 docs/development.md；代码任务先执行 harness task start。"
        }
    task_path = root / ".harness/task.json"
    task = read_json(task_path)
    if not task.get("active"):
        return {}
    current = cli.fingerprint()
    if event == "PostToolUse":
        task["dirty"] = task.get("verified_fingerprint") != current
        task_path.write_text(json.dumps(task, indent=2), encoding="utf-8")
        return {}
    if event == "Stop":
        scope = task.get("scope", "affected")
        if scope not in REQUIRED:
            scope = "affected"
        if verified(read_json(root / ".harness/latest.json"), scope, current):
            task.update(active=False, verified_fingerprint=current, dirty=False)
            task_path.write_text(json.dumps(task, indent=2), encoding="utf-8")
            return {}
        reason = f"代码任务缺少有效的 {scope} 检查。运行 python -m uv run --locked harness check --scope {scope}，修复失败后记录真实结果。"
        if data.get("stop_hook_active"):
            return {"systemMessage": reason + " 已续跑过一次，保持未完成并报告阻碍，避免循环。"}
        return {"decision": "block", "reason": reason}
    return {}


def main(root: Path = cli.ROOT):
    try:
        payload = json.load(sys.stdin)
    except (ValueError, EOFError):
        payload = {}
    result = handle(sys.argv[1], payload if isinstance(payload, dict) else {}, root)
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
