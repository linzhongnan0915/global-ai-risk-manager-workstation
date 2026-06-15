"""Tests for Render / public demo hosting helpers."""

from __future__ import annotations

import pytest

from src.market.demo_hosting import (
    configure_yfinance_cache,
    demo_scheduler_label,
    intraday_scheduler_enabled,
    is_demo_hosting,
)


def test_is_demo_hosting_env(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("PUBLIC_DEMO", raising=False)
    assert is_demo_hosting() is False
    monkeypatch.setenv("RENDER", "true")
    assert is_demo_hosting() is True


def test_intraday_scheduler_disabled_on_demo_by_default(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("ENABLE_INTRADAY_SCHEDULER", raising=False)
    assert intraday_scheduler_enabled(config_enabled=True, force_start=None, force_disable=False) is False


def test_intraday_scheduler_can_be_enabled_on_demo(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("ENABLE_INTRADAY_SCHEDULER", "1")
    assert intraday_scheduler_enabled(config_enabled=True, force_start=None, force_disable=False) is True


def test_demo_scheduler_label_manual_when_disabled(monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO", "1")
    assert demo_scheduler_label(False) == "Manual refresh only while service is running"
    assert demo_scheduler_label(True) == "Scheduler active while service is running"


def test_configure_yfinance_cache(tmp_path, monkeypatch):
    cache_dir = tmp_path / "yf-cache"
    monkeypatch.setenv("YFINANCE_CACHE_DIR", str(cache_dir))
    configure_yfinance_cache(tmp_path)
    assert cache_dir.exists()
