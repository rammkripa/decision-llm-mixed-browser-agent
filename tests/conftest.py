"""Fail closed if an offline regression accidentally reaches a paid model transport."""

import httpx
import pytest


@pytest.fixture(autouse=True)
def forbid_model_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Offline tests must not call live HTTP APIs")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
