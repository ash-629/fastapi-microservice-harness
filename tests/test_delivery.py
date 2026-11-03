import zipfile

import pytest
from harness import cli, delivery, hooks


def test_package_excludes_local_artifacts_and_preserves_hidden_skills(tmp_path, monkeypatch):
    root = tmp_path / "demo"
    root.mkdir()
    monkeypatch.setattr(cli, "ROOT", root)
    for name in [
        ".agents/skills/demo/SKILL.md",
        "README.md",
        ".venv/lib/x.py",
        "web/node_modules/x.js",
        ".runtime/orders.sqlite3",
        ".env",
        ".git/config",
        "debug.log",
    ]:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("demo")
    report = {
        "status": "PASS",
        "fingerprint": cli.fingerprint(),
        "checks": [{"name": c, "status": "PASS"} for c in hooks.REQUIRED["full"]],
    }
    p = root / ".harness/latest.json"
    p.parent.mkdir()
    import json

    p.write_text(json.dumps(report))
    out = delivery.package(root, tmp_path / "delivery.zip")
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "OrderStudio/demo/.agents/skills/demo/SKILL.md" in names
        assert not any(
            x in name
            for name in names
            for x in ["node_modules", ".venv", ".env", ".git/", ".sqlite3", "debug.log"]
        )
    with pytest.raises(ValueError, match="exists"):
        delivery.package(root, out)


def test_delivery_requires_valid_current_full_report(tmp_path, monkeypatch):
    root = tmp_path / "demo"
    root.mkdir()
    monkeypatch.setattr(cli, "ROOT", root)
    with pytest.raises(RuntimeError, match="full"):
        delivery.package(root, tmp_path / "out.zip")
