"""验证 Git index 快照，不 stash，不修改工作区，不复用工作区源码导入。"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .cli import ROOT, run


def check_staged():
    dependency_root = Path(os.environ.get("HARNESS_DEPENDENCY_ROOT", str(ROOT)))
    with tempfile.TemporaryDirectory(prefix="harness-index-") as folder:
        snapshot = Path(folder)
        run(["git", "checkout-index", "--all", "--prefix=" + snapshot.as_posix() + "/"])
        for name in ["pyproject.toml", "uv.lock", "tools/harness/cli.py", "web/package-lock.json"]:
            if not (snapshot / name).exists():
                raise RuntimeError(f"Staged snapshot is incomplete: {name}; stage required files")
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            str(snapshot / p) for p in ["tools", "services/orders/src", "services/inventory/src"]
        )
        env["HARNESS_DEPENDENCY_ROOT"] = str(dependency_root)
        # 解释器依赖可复用；所有项目源必须从 index 快照导入。
        for command in [
            [sys.executable, "-m", "ruff", "check", "."],
            [sys.executable, "-m", "ruff", "format", "--check", "."],
            [
                sys.executable,
                "-c",
                "from harness.cli import ROOT,architecture,contract; "
                "from pathlib import Path; "
                'assert ROOT==Path.cwd(),"source import escaped index snapshot"; '
                "architecture();contract()",
            ],
        ]:
            subprocess.run(command, cwd=snapshot, env=env, check=True, shell=False)
        print("Staged snapshot: static, architecture, OpenAPI and generated client checks PASS")
