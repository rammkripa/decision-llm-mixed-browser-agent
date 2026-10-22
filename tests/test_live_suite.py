"""Suite orchestration only: no browser or paid API calls."""

import json
from datetime import date

import pytest

from jev_ultrafast import live_suite


def test_suite_continues_after_failure_and_saves_separate_runs(monkeypatch, tmp_path):
    calls = []

    def run(task, folder, headless):
        calls.append((task['id'], folder, headless))
        return {**task, 'returncode': int(len(calls) == 1),
                'status': 'error' if len(calls) == 1 else 'done'}

    monkeypatch.setattr(live_suite, 'run_case', run)
    assert live_suite.main(['--output', str(tmp_path), '--headfull', '--only',
                            'wikipedia-webb', 'books-identifiers', '--repeat', '2']) == 1
    assert [c[0] for c in calls] == ['wikipedia-webb', 'books-identifiers'] * 2
    assert len({c[1] for c in calls}) == 4
    assert all(not c[2] for c in calls)
    summary = json.loads(next(tmp_path.glob('*/summary.json')).read_text())
    assert summary['outcomes'] == {'error': 1, 'done': 3}
    assert summary['status'] == 'finished'


def test_list_never_launches_models(monkeypatch):
    monkeypatch.setattr(live_suite, 'run_case', lambda *_: pytest.fail('Should not run'))
    assert live_suite.main(['--list']) == 0


def test_flight_date_is_explicit_in_goal():
    assert '2027-01-20' in live_suite.cases(date(2027, 1, 20).isoformat())[0]['goal']


def test_unknown_case_is_rejected(tmp_path):
    with pytest.raises(SystemExit):
        live_suite.main(['--only', 'unknown', '--output', str(tmp_path)])
    assert not list(tmp_path.iterdir())


def test_missing_trace_records_startup_failure(monkeypatch, tmp_path):
    from unittest.mock import Mock

    child = Mock()
    child.wait.return_value = 1
    child.stdout.fileno.return_value = 99
    process = Mock()
    process.__enter__ = Mock(return_value=child)
    process.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(live_suite.subprocess, 'Popen', lambda *_args, **_kwargs: process)
    chunks = iter([b'Planning connection failed\n', b''])
    monkeypatch.setattr(live_suite.os, 'read', lambda *_: next(chunks))
    task = live_suite.cases('2026-12-20')[0]
    report = live_suite.run_case(task, tmp_path, True)
    assert report['status'] == 'error' and report['returncode'] == 1
    assert 'trace_error' in report
    assert (tmp_path / 'terminal.log').read_text() == 'Planning connection failed\n'
    assert json.loads((tmp_path / 'result.json').read_text())['independent_verification'] == 'not_run'
