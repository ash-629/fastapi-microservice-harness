"""仅检查仓库本地 Markdown 引用；不请求外部站点。"""

import re
from pathlib import Path


def check(root: Path):
    for path in [root / "README.md", *list((root / "docs").rglob("*.md"))]:
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#")):
                continue
            if not (path.parent / target.split("#", 1)[0]).exists():
                raise RuntimeError(f"Broken link: {path.relative_to(root)} -> {target}")
