import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_read_env_uses_utf8_for_non_ascii_values(tmp_path, monkeypatch):
    from api import settings

    env_path = tmp_path / ".env"
    env_path.write_text("# 注释 🔐\nOPENAI_MODEL=模型🔐\n", encoding="utf-8")
    monkeypatch.setattr(settings, "ENV_PATH", env_path)

    assert settings._read_env()["OPENAI_MODEL"] == "模型🔐"


def test_write_env_uses_utf8_for_non_ascii_values(tmp_path, monkeypatch):
    from api import settings

    env_path = tmp_path / ".env"
    monkeypatch.setattr(settings, "ENV_PATH", env_path)

    settings._write_env({"OPENAI_MODEL": "模型🔐"})

    assert "OPENAI_MODEL=模型🔐" in env_path.read_text(encoding="utf-8")
