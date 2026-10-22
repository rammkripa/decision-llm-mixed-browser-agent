import json
from unittest.mock import Mock

from jev_ultrafast.web import Runs, run_request


def test_local_runs_keep_controls_and_results_separate(tmp_path, monkeypatch):
    consoles = []

    def make_console(root):
        console = Mock()
        suffix = ('a' if not consoles else 'b') * 32
        console.start.return_value = {'run_id': suffix}
        console.snapshot.return_value = {'run_id': suffix, 'goal': suffix, 'status': 'running'}
        consoles.append(console)
        return console

    monkeypatch.setattr('jev_ultrafast.web.Console', make_console)
    runs = Runs(tmp_path)
    first = runs.start({'goal': 'first'})
    second = runs.start({'goal': 'second'})
    assert first['run_id'] != second['run_id']
    assert runs.snapshot(first['run_id'])['goal'] == 'a' * 32
    assert runs.snapshot(second['run_id'])['goal'] == 'b' * 32
    runs.control(first['run_id'], 'cancel')
    consoles[0].control.assert_called_once_with('cancel')
    consoles[1].control.assert_not_called()
    assert runs.get('../other') is None
    runs.close()
    for console in consoles:
        console.close.assert_called_once()


def test_local_finished_run_reopens_from_its_own_audit_folder(tmp_path):
    suffix = 'a' * 32
    folder = tmp_path / suffix
    folder.mkdir()
    (folder / 'console.json').write_text(json.dumps({'run_id': suffix, 'goal': 'saved task', 'status': 'done'}))
    runs = Runs(tmp_path)
    state = runs.snapshot('minotaur-' + suffix)
    assert state['goal'] == 'saved task'
    assert state['run_id'] == 'minotaur-' + suffix
    assert runs.get('minotaur-' + 'b' * 32) is None


def test_run_routes_select_the_requested_run():
    run_id = 'minotaur-' + 'a' * 32
    for action in ('state', 'control', 'trace'):
        assert run_request(f'/api/runs/{run_id}/{action}') == (f'/api/{action}', run_id)
    assert run_request('/api/state') == ('/api/state', None)
