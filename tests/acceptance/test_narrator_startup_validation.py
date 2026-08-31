"""
Source: env-config plan -- packages/config/env.validate_startup().

A misconfigured narrator (backend=gemini, no key) must surface a loud
warning at startup instead of silently running on the template. The key
value itself is never included in a warning.
"""

from __future__ import annotations

import packages.config.env as env


def test_backend_gemini_without_key_warns(monkeypatch):
    monkeypatch.setenv("NARRATOR_BACKEND", "gemini")
    monkeypatch.setenv("NARRATOR_ENABLED", "true")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    warnings = env.validate_startup()
    assert any("GEMINI_API_KEY is missing or blank" in w for w in warnings)


def test_blank_key_is_treated_as_missing(monkeypatch):
    monkeypatch.setenv("NARRATOR_BACKEND", "gemini")
    monkeypatch.setenv("NARRATOR_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    assert any("missing or blank" in w for w in env.validate_startup())


def test_key_set_but_backend_not_gemini_warns_without_echoing_key(monkeypatch):
    monkeypatch.setenv("NARRATOR_BACKEND", "template")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaTOPSECRET")
    warnings = env.validate_startup()
    assert any("the key is unused" in w for w in warnings)
    assert all("AIzaTOPSECRET" not in w for w in warnings)


def test_unknown_backend_warns(monkeypatch):
    monkeypatch.setenv("NARRATOR_BACKEND", "gpt-5")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert any("not a known backend" in w for w in env.validate_startup())


def test_gemini_disabled_warns(monkeypatch):
    monkeypatch.setenv("NARRATOR_BACKEND", "gemini")
    monkeypatch.setenv("NARRATOR_ENABLED", "false")
    monkeypatch.setenv("GEMINI_API_KEY", "present")
    assert any("NARRATOR_ENABLED=false" in w for w in env.validate_startup())


def test_fully_configured_is_clean(monkeypatch):
    monkeypatch.setenv("NARRATOR_BACKEND", "gemini")
    monkeypatch.setenv("NARRATOR_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "present")
    assert env.validate_startup() == []


def test_template_default_is_clean(monkeypatch):
    monkeypatch.delenv("NARRATOR_BACKEND", raising=False)
    monkeypatch.delenv("NARRATOR_ENABLED", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert env.validate_startup() == []


def test_key_value_never_appears_in_any_warning(monkeypatch):
    monkeypatch.setenv("NARRATOR_BACKEND", "gemini")
    monkeypatch.setenv("NARRATOR_ENABLED", "false")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSUPERSECRETVALUE")
    for w in env.validate_startup():
        assert "AIzaSUPERSECRETVALUE" not in w
