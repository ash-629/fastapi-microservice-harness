"""创建源码归档，排除依赖、运行数据、日志和 Git 元数据。"""

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
        raise ValueError("Place source archive outside the project directory")
    if output.exists():
        raise ValueError("Output exists; choose a new filename to preserve the previous archive")
    report = read_json(root / ".harness/latest.json")
    if not verified(report, "full", fingerprint()):
        raise RuntimeError("Run a successful full check on current sources before packaging")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in source_files(root):
            info = zipfile.ZipInfo("OrderStudio/demo/" + path.relative_to(root).as_posix())
            info.external_attr = (0o100755 if ".githooks" in path.parts else 0o100644) << 16
            archive.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr(
            "OrderStudio/README.md",
            "# Order Studio\n\n安装、运行与开发说明见 [README](demo/README.md)。\n",
        )
        archive.writestr(
            "OrderStudio/check-results.json", json.dumps(report, ensure_ascii=False, indent=2)
        )
    return output
