"""交付源码选择与干净打包；依赖、数据库、日志和 Git 元数据不进入压缩包。"""

import json
import os
import zipfile
from pathlib import Path

EXCLUDED = {
    ".git",
    ".venv",
    "node_modules",
    ".runtime",
    ".harness",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".vite",
    "dist",
    "test-results",
    "playwright-report",
}


def source_files(root: Path):
    for parent, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED)
        for name in sorted(files):
            path = Path(parent) / name
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise RuntimeError(f"Unexpected source link: {path}")
            if name.startswith(".env") and name != ".env.example":
                continue
            if path.suffix.lower() in {".log", ".db", ".sqlite3", ".zip", ".pyc"}:
                continue
            yield path


def package(root: Path, output: Path):
    from .cli import fingerprint
    from .hooks import read_json, verified

    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError("Place delivery archive outside the source project")
    if output.exists():
        raise ValueError("Output exists; choose a new filename to preserve previous delivery")
    report = read_json(root / ".harness/latest.json")
    if not verified(report, "full", fingerprint()):
        raise RuntimeError("Run a successful full check on current sources before packaging")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in source_files(root):
            info = zipfile.ZipInfo("OrderStudio/demo/" + path.relative_to(root).as_posix())
            info.external_attr = (0o100755 if ".githooks" in path.parts else 0o100644) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
        design = root.parent / "方案与设计_v1.0_20261103.md"
        if design.exists():
            archive.write(design, "OrderStudio/方案与设计.md")
        archive.writestr(
            "OrderStudio/README.md",
            "# Order Studio\n\n从 [项目说明](demo/README.md) 开始。\n\n[原始方案与设计](方案与设计.md) 是设计基线，实际实现与限制以项目 README 和 QA_REPORT.md 为准。\n",
        )
        archive.writestr(
            "OrderStudio/验收摘要.json", json.dumps(report, ensure_ascii=False, indent=2)
        )
    return output
