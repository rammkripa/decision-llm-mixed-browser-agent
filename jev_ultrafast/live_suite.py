"""Opt-in sequential live-model smoke suite. Offline pytest never invokes live providers."""

import argparse
import codecs
import json
import os
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


def cases(flight_date):
    return [
        {'id': 'flights', 'url': 'https://www.google.com/travel/flights?hl=en',
         'goal': f'Find one-way flights from Zurich to London on {flight_date}, for one adult in economy. '
                 'Report the top three available options with airline, departure and arrival times, and prices.'},
        {'id': 'python-search', 'url': 'https://www.google.com',
         'goal': "Find Python's official documentation explaining list.sort() and sorted(). Explain which "
                 'modifies the original list and which returns a new list, with the documentation URL.'},
        {'id': 'wikipedia-webb', 'url': 'https://en.wikipedia.org/wiki/Main_Page',
         'goal': 'James Webb Space Telescope: Report its launch date, the launch vehicle, and why it operates '
                 'near the Sun-Earth L2 point. Cite supporting sources.'},
        {'id': 'wikipedia-godel', 'url': 'https://en.wikipedia.org/wiki/Main_Page',
         'goal': "Find and summarize Gödel’s incompleteness theorems, including their assumptions, with sources."},
        {'id': 'books-identifiers', 'url': 'https://books.toscrape.com',
         'goal': 'Find the product page for A Light in the Attic. Report its title, price, and UPC. Check whether '
                 'an ISBN is listed; if it is absent, say that this page does not provide one.'},
        {'id': 'books-first-five', 'url': 'https://books.toscrape.com',
         'goal': 'Report the full titles and displayed prices of the first five books on this page.'},
        {'id': 'books-travel', 'url': 'https://books.toscrape.com',
         'goal': 'Find the cheapest book in the Travel category. Report its full title, displayed price, '
                 'and product page URL.'},
    ]


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False))
    temporary.replace(path)


def run_case(task, folder, headless):
    trace_path, log_path = folder / 'trace.json', folder / 'terminal.log'
    command = [sys.executable, '-u', '-m', 'jev_ultrafast.cli',
               '--headless' if headless else '--headfull', '--url', task['url'],
               '--goal', task['goal'], '--trace', str(trace_path)]
    write_json(folder / 'task.json', task)
    started = time.monotonic()
    with log_path.open('wb') as log:
        # Inherit stdin so visible Chrome's CAPTCHA handoff still works in a terminal.
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as child:
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            try:
                while chunk := os.read(child.stdout.fileno(), 4096):
                    log.write(chunk)
                    log.flush()
                    sys.stdout.write(decoder.decode(chunk))
                    sys.stdout.flush()
                sys.stdout.write(decoder.decode(b'', final=True))
                returncode = child.wait()
            except KeyboardInterrupt:
                # Allow the CLI supervisor to clean up its owned Chrome before exiting.
                child.wait()
                raise
    report = {**task, 'returncode': returncode, 'duration_ms': round((time.monotonic() - started) * 1000),
              'trace': str(trace_path), 'log': str(log_path), 'status': 'error',
              'independent_verification': 'not_run'}
    try:
        trace = json.loads(trace_path.read_text())
        if trace.get('goal') != task['goal']:
            raise ValueError('Trace goal does not match this task')
        report.update(status=trace.get('status', 'error'), blocked_reason=trace.get('blocked_reason'),
                      model_calls=trace.get('model_calls', {}), models=trace.get('models'),
                      source_hashes=trace.get('source_hashes'), result=trace.get('result'),
                      evidence_count=len(trace.get('evidence', [])), browser_actions=len(trace.get('history', [])),
                      event_counts=dict(Counter(e.get('status', 'unknown') for e in trace.get('research_events', []))),
                      verification=trace.get('verification', []), answer_attempts=trace.get('answer_attempts', []))
    except (OSError, ValueError, TypeError) as exc:
        report['trace_error'] = str(exc)
    if returncode != 0 and report['status'] == 'done':
        report['status'] = 'error'
    write_json(folder / 'result.json', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run opt-in live browser tasks sequentially (paid model calls).')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--headfull', dest='headless', action='store_false')
    modes.add_argument('--headless', dest='headless', action='store_true')
    parser.set_defaults(headless=True)
    parser.add_argument('--output', default='artifacts/live-suite')
    parser.add_argument('--only', nargs='+', help='Task IDs to run; use --list to see IDs.')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--flight-date', type=date.fromisoformat, default=date.today() + timedelta(days=60))
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args(argv)
    tasks = cases(args.flight_date.isoformat())
    if args.list:
        for task in tasks:
            print(task['id'] + ': ' + task['goal'])
        return 0
    if args.repeat < 1:
        parser.error('--repeat must be positive')
    if args.only:
        unknown = set(args.only) - {t['id'] for t in tasks}
        if unknown:
            parser.error('Unknown task IDs: ' + ', '.join(sorted(unknown)))
        tasks = [t for t in tasks if t['id'] in args.only]
    root = Path(args.output).resolve() / datetime.now(UTC).strftime('%Y%m%dT%H%M%S.%fZ')
    root.mkdir(parents=True, exist_ok=False)
    summary = {'started_at': datetime.now(UTC).isoformat(), 'status': 'running',
               'browser_mode': 'headless' if args.headless else 'headfull',
               'flight_date': args.flight_date.isoformat(), 'tasks': tasks, 'repeat': args.repeat, 'results': []}
    write_json(root / 'summary.json', summary)
    print(f'Live suite: {len(tasks) * args.repeat} runs; paid models. Results: {root}', flush=True)
    try:
        for repetition in range(1, args.repeat + 1):
            for task in tasks:
                folder = root / f'{repetition:02d}-{task["id"]}'
                folder.mkdir()
                print(f'\nRunning {task["id"]} ({repetition}/{args.repeat})', flush=True)
                report = run_case(task, folder, args.headless)
                summary['results'].append({**report, 'repetition': repetition})
                write_json(root / 'summary.json', summary)
    except KeyboardInterrupt:
        summary['status'] = 'interrupted'
        raise
    finally:
        if summary['status'] == 'running':
            summary['status'] = 'finished'
        summary['finished_at'] = datetime.now(UTC).isoformat()
        summary['outcomes'] = dict(Counter(r['status'] for r in summary['results']))
        write_json(root / 'summary.json', summary)
        print(f'\nSummary: {root / "summary.json"}', flush=True)
    return int(any(r['returncode'] or r['status'] != 'done' for r in summary['results']))


if __name__ == '__main__':
    raise SystemExit(main())
