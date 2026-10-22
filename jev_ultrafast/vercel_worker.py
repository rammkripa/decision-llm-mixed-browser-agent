"""Run one task outside the Vercel request lifetime and preserve its audit files."""

import json
import signal
import sys
import time
from pathlib import Path

from .browserbase import Browserbase
from .web import Console
from .web_worker import save


def main():
    root = Path('/vercel/sandbox')
    console = Console(root / 'runs')
    if '--release' in sys.argv:
        console.state = json.loads((root / 'state.json').read_text())
        console.client = Browserbase()
        console.release()
        save(root / 'state.json', console.snapshot())
        return

    def stop(_signum, _frame):
        console.close()
        save(root / 'state.json', console.snapshot())
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    try:
        console.start(json.loads((root / 'task.json').read_text()))
        while console.thread.is_alive():
            state = console.snapshot()
            if state['status'] in {'done', 'blocked', 'error', 'cancelled'}:
                state['status'] = 'closing'
            save(root / 'state.json', state)
            for action in ('cancel', 'pause', 'resume', 'release'):
                marker = root / action
                if marker.exists():
                    marker.unlink()
                    try:
                        console.control(action)
                    except ValueError:
                        pass
            time.sleep(.5)
        if console.folder and (console.folder / 'trace.json').exists():
            (root / 'trace.json').write_bytes((console.folder / 'trace.json').read_bytes())
        save(root / 'state.json', console.snapshot())
    except Exception as exc:
        console.update(status='error', blocked_reason=str(exc))
        save(root / 'trace.json', console.snapshot())
        save(root / 'state.json', console.snapshot())
    finally:
        console.close()


if __name__ == '__main__':
    main()
