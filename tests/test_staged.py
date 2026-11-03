"""工作区修好但未暂存时，Hook 必须仍拒绝 index 中的错误版本。"""

import os
import shutil
import subprocess
import sys

from harness.cli import ROOT
from harness.packaging import source_files


def test_staged_checks_index_not_worktree(tmp_path):
    snapshot = tmp_path / "repo"
    snapshot.mkdir()
    for path in source_files(ROOT):
        target = snapshot / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)

    def git(*args):
        subprocess.run(["git", *args], cwd=snapshot, check=True, capture_output=True)

    git("init")
    probe = snapshot / "services/orders/src/order_service/index_probe.py"
    probe.write_text("import inventory_service as inventory_service\n")
    git("add", ".")
    probe.write_text("# Fixed in worktree, but not staged yet.\n")
    env = dict(
        os.environ,
        HARNESS_DEPENDENCY_ROOT=str(ROOT),
        PYTHONPATH=os.pathsep.join(
            str(snapshot / p) for p in ["tools", "services/orders/src", "services/inventory/src"]
        ),
    )

    def check():
        return subprocess.run(
            [sys.executable, "-m", "harness.cli", "staged"],
            cwd=snapshot,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    bad = check()
    assert bad.returncode != 0 and "cross-service import" in bad.stderr
    assert probe.read_text().startswith("# Fixed")
    git("add", ".")
    good = check()
    assert good.returncode == 0, good.stdout + good.stderr
