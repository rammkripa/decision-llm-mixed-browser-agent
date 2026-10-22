"""Browser-mode CLI contracts; no browser startup or model requests."""

from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from jev_ultrafast import cli, launch


@pytest.mark.parametrize("flags,headless", [([], True), (["--headless"], True), (["--headfull"], False)])
def test_mode_defaults_and_flags(flags, headless):
    args = cli.parser().parse_args(["--url", "https://example.test", "--goal", "Read the page", *flags])
    assert args.headless is headless


def test_modes_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--url", "https://example.test", "--goal", "Read", "--headless", "--headfull"])


@pytest.mark.parametrize("headless", [True, False])
def test_chrome_command_uses_real_headless_mode_and_isolated_profile(headless):
    command = launch.chrome_command("/chrome", "/tmp/profile with spaces", headless=headless)
    assert ("--headless=new" in command) is headless
    assert "--user-data-dir=/tmp/profile with spaces" in command
    assert "--remote-debugging-port=0" in command
    assert "--remote-debugging-address=127.0.0.1" in command


def test_supervisor_passes_named_connection_before_worker_import(monkeypatch):
    @contextmanager
    def browser(**kwargs):
        assert kwargs == {"headless": False}
        yield {"BU_NAME": "owned-test", "BU_CDP_URL": "http://127.0.0.1:1234"}

    monkeypatch.setattr(cli, "launched_browser", browser)
    run = Mock(return_value=Mock(returncode=7))
    monkeypatch.setattr(cli.subprocess, "run", run)
    assert cli.main(["--url", "https://example.test", "--goal", "Read", "--headfull"]) == 7
    command = run.call_args.args[0]
    assert "--browser-worker" in command and "--headfull" in command
    assert run.call_args.kwargs["env"]["BU_NAME"] == "owned-test"


def test_missing_explicit_binary_is_actionable(monkeypatch):
    monkeypatch.setenv("JEV_CHROME_BIN", "/does/not/exist/chrome")
    with pytest.raises(RuntimeError, match="JEV_CHROME_BIN"):
        launch.chrome_binary()


def test_visible_handoff_waits_for_user(monkeypatch):
    monkeypatch.setattr(cli.sys.stdin, 'isatty', lambda: True)
    prompt = Mock(return_value='')
    monkeypatch.setattr('builtins.input', prompt)
    assert cli.human_handoff({'url': 'https://example.test/challenge'}, headless=False)
    prompt.assert_called_once()
    prompt.return_value = 'q'
    assert not cli.human_handoff({'url': 'https://example.test/challenge'}, headless=False)


def test_headless_handoff_never_prompts(monkeypatch):
    prompt = Mock()
    monkeypatch.setattr('builtins.input', prompt)
    assert not cli.human_handoff({'url': 'https://example.test/challenge'}, headless=True)
    prompt.assert_not_called()
