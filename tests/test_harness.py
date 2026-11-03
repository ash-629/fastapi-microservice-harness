from harness import cli
import pytest


def test_fingerprint_and_architecture(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    for s in ["orders", "inventory"]:
        (tmp_path / "services" / s / "src").mkdir(parents=True)
    p = tmp_path / "services/orders/src/x.py"
    p.write_text("x=1")
    before = cli.fingerprint()
    p.write_text("x=2")
    assert before != cli.fingerprint()
    p.write_text("import inventory_service")
    with pytest.raises(RuntimeError, match="cross-service"):
        cli.architecture()


def test_hook_adapter_protocol(tmp_path):
    import subprocess
    import json
    import sys

    for event in ["SessionStart", "PostToolUse", "Stop"]:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; from harness.hooks import main; import sys; main(Path(sys.argv[2]))",
                event,
                str(tmp_path),
            ],
            input="{}",
            text=True,
            capture_output=True,
            encoding="utf-8",
            check=True,
        )
        assert isinstance(json.loads(result.stdout), dict)
