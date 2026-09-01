import pytest

from config import Settings


@pytest.fixture(autouse=True)
def isolate_tests_from_local_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests must never depend on or expose a developer's live .env."""

    monkeypatch.setitem(Settings.model_config, "env_file", None)
