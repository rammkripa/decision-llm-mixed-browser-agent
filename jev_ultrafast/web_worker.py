"""One remote research run per process, with immutable audit and compact UI snapshots."""

import argparse
import json
import os
import re
import time
from pathlib import Path

from .research import ResearchAgent


def redact(value):
    if isinstance(value, str):
        for name in ('BROWSERBASE_API_KEY', 'TEXT_MODEL_API_KEY', 'TYPESAFE_API_KEY', 'BU_CDP_WS'):
            secret = os.environ.get(name)
            if secret:
                value = value.replace(secret, '[redacted]')
        return re.sub(r'wss?://[^\s"\']+', '[private browser connection]', value)
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def save(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(redact(data), ensure_ascii=False))
    temporary.replace(path)


def present(state, target=None):
    events = []
    for event in state.get('research_events', [])[-100:]:
        decision = event.get('resolved_decision', event.get('decision', {}))
        events.append({'status': event['status'], 'operation': decision.get('operation'),
                       'target': decision.get('target'), 'task': event.get('task'),
                       'passage': event.get('passage', {}).get('text', '')[:180],
                       'reason': event.get('reason', event.get('resolution_error'))})
    return {'status': state.get('status', 'running'), 'elapsed_ms': state.get('elapsed_ms', 0),
            'tasks': state.get('tasks', []), 'task_index': state.get('task_index', 0),
            'history': [{k: h.get(k) for k in ('step', 'action', 'operation', 'text', 'page_changed', 'elapsed_ms')}
                        for h in state.get('history', [])],
            'events': events, 'evidence_count': len(state.get('evidence', [])),
            'model_calls': state.get('model_calls', {}), 'result': state.get('result'),
            'blocked_reason': state.get('blocked_reason'), 'target_id': target,
            'page': {k: state.get('page', {}).get(k) for k in ('url', 'title')}}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', required=True)
    args = parser.parse_args(argv)
    folder = Path(args.folder)
    task = json.loads((folder / 'task.json').read_text())
    agent = None
    started = time.monotonic()
    latest = {'status': 'planning', 'tasks': [], 'history': [], 'evidence_count': 0}

    def publish(state=None, **changes):
        nonlocal latest
        if state is not None:
            latest = present(state, agent.runner.browser.target)
        latest.update(changes)
        save(folder / 'progress.json', latest)

    def handoff(_page):
        (folder / 'resume').unlink(missing_ok=True)
        publish(status='awaiting_human')
        while not (folder / 'cancel').exists():
            if (folder / 'resume').exists():
                (folder / 'resume').unlink(missing_ok=True)
                (folder / 'pause').unlink(missing_ok=True)
                publish(status='running')
                return True
            time.sleep(.25)
        return False

    publish()
    try:
        agent = ResearchAgent(task['url'], task['goal'], human_handoff=handoff)
        agent.runner.browser.call('Page.bringToFront')
        publish(agent.snapshot())
        for state in agent.run():
            publish(state)
            if (folder / 'cancel').exists():
                publish(status='cancelled')
                break
            if (folder / 'pause').exists() and state['status'] not in {'done', 'blocked'}:
                if not handoff(None):
                    publish(status='cancelled')
                    break
                agent.runner.state['decision'] = None
                agent.runner.pending_text = None
    except Exception as exc:
        publish(status='error', blocked_reason=str(exc))
    finally:
        if (folder / 'cancel').exists():
            publish(status='cancelled')
        trace = agent.snapshot() if agent else {'goal': task['goal'], 'status': 'error'}
        trace.update(status=latest['status'], blocked_reason=latest.get('blocked_reason'),
                     wall_elapsed_ms=round((time.monotonic() - started) * 1000), browser_mode='browserbase')
        save(folder / 'trace.json', trace)
        try:
            if agent:
                agent.close()
        finally:
            from browser_harness.admin import restart_daemon

            restart_daemon(os.environ['BU_NAME'])
    return 0 if latest['status'] == 'done' else 1


if __name__ == '__main__':
    raise SystemExit(main())
