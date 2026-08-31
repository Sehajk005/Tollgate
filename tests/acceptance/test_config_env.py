"""
Source: env-config plan -- packages/config/env.py.

Covers the .env loader (override=False, missing-file no-op, skip flag) and
proves every accessor reads os.environ at call time -- eval/corpus.py writes
NARRATOR_ENABLED at runtime and the narrator acceptance tests monkeypatch
after import, so a cached settings object would break them.
"""

from __future__ import annotations

import packages.config.env as env


def _load(monkeypatch, tmp_path):
    """load_env_file() with tmp_path as CWD, bypassing the once-per-process guard."""
    monkeypatch.chdir(tmp_path)
    return env.load_env_file(force=True)


class TestLoadEnvFile:
    def test_missing_env_file_is_a_noop(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert _load(monkeypatch, tmp_path) is None
        assert env.gemini_api_key() == ""

    def test_env_file_loaded_when_var_unset(self, tmp_path, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        (tmp_path / ".env").write_text("GEMINI_API_KEY=from-dotenv\n", encoding="utf-8")
        assert _load(monkeypatch, tmp_path) is not None
        assert env.gemini_api_key() == "from-dotenv"

    def test_real_environment_wins_over_env_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "from-real-env")
        (tmp_path / ".env").write_text("GEMINI_API_KEY=from-dotenv\n", encoding="utf-8")
        _load(monkeypatch, tmp_path)
        assert env.gemini_api_key() == "from-real-env"

    def test_skip_flag_disables_loading(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TOLLGATE_SKIP_DOTENV", "1")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        (tmp_path / ".env").write_text("GEMINI_API_KEY=from-dotenv\n", encoding="utf-8")
        assert _load(monkeypatch, tmp_path) is None
        assert env.gemini_api_key() == ""


class TestAccessorsAreDynamic:
    def test_accessors_reflect_env_set_after_load(self, tmp_path, monkeypatch):
        _load(monkeypatch, tmp_path)  # no .env present
        monkeypatch.setenv("NARRATOR_BACKEND", "gemini")
        monkeypatch.setenv("NARRATOR_ENABLED", "false")
        assert env.narrator_backend() == "gemini"
        assert env.narrator_enabled() is False
        monkeypatch.setenv("NARRATOR_ENABLED", "true")
        assert env.narrator_enabled() is True


class TestGeminiModelsLadder:
    def test_default_chain_when_nothing_set(self, monkeypatch):
        monkeypatch.delenv("GEMINI_MODELS", raising=False)
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        assert env.gemini_models() == env.DEFAULT_MODELS

    def test_legacy_single_model_is_a_one_element_chain(self, monkeypatch):
        monkeypatch.delenv("GEMINI_MODELS", raising=False)
        monkeypatch.setenv("GEMINI_MODEL", "gemini-1.5-flash")
        assert env.gemini_models() == ("gemini-1.5-flash",)

    def test_plural_wins_and_is_split_and_trimmed(self, monkeypatch):
        monkeypatch.setenv("GEMINI_MODEL", "ignored-when-plural-present")
        monkeypatch.setenv("GEMINI_MODELS", " a , b ,, c ")
        assert env.gemini_models() == ("a", "b", "c")
