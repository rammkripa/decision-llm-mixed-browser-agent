"""Run the hybrid agent; persist its complete trace locally, including on failure."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .launch import launched_browser
from .research import ResearchAgent


def parser():
    result = argparse.ArgumentParser(description="Run a task with an isolated local Chrome browser.")
    result.add_argument("--url", required=True)
    result.add_argument("--goal", required=True)
    result.add_argument("--trace", default="artifacts/research.json")
    modes = result.add_mutually_exclusive_group()
    modes.add_argument("--headless", dest="headless", action="store_true", help="Hide Chrome (default).")
    modes.add_argument("--headfull", dest="headless", action="store_false", help="Show Chrome while the task runs.")
    result.set_defaults(headless=True)
    result.add_argument("--browser-worker", action="store_true", help=argparse.SUPPRESS)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if args.browser_worker:
        return run_worker(args)
    print("Launching " + ("headless" if args.headless else "visible") + " Chrome with an isolated profile.", flush=True)
    with launched_browser(headless=args.headless) as env:
        command = [sys.executable, "-u", "-m", "jev_ultrafast.cli", "--browser-worker",
                   "--headless" if args.headless else "--headfull", "--url", args.url,
                   "--goal", args.goal, "--trace", args.trace]
        return subprocess.run(command, env=env, check=False).returncode


def human_handoff(page, *, headless):
    if headless or not sys.stdin.isatty():
        return False
    print("\nHuman verification required at " + page["url"], flush=True)
    print("Solve the CAPTCHA in Chrome. The agent is paused and will not interact with it.", flush=True)
    try:
        return input("Press Enter here when finished, or type q to stop: ").strip().lower() != "q"
    except EOFError:
        return False


def run_worker(args):
    destination = Path(args.trace)
    destination.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    root = Path(__file__).resolve().parents[1]
    sources = ["jev_ultrafast/agent.py", "jev_ultrafast/model.py", "jev_ultrafast/research.py",
               "jev_ultrafast/browser.py", "jev_ultrafast/snapshot.js", "jev_ultrafast/content.js",
               "jev_ultrafast/static/research.html", "jev_ultrafast/static/research_policy.html",
               "jev_ultrafast/cli.py", "jev_ultrafast/launch.py"]
    metadata = {"browser_mode": "headless" if args.headless else "headfull",
                "models": {"decision": os.environ.get("TYPESAFE_MODEL", "jev-latest"),
                           "text": os.environ.get("TEXT_MODEL", "deepseek-chat")},
                "source_hashes": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources}}
    with ResearchAgent(args.url, args.goal,
                       human_handoff=lambda page: human_handoff(page, headless=args.headless)) as agent:
        if not args.headless:
            agent.runner.browser.call("Page.bringToFront")
        try:
            for state in agent.run():
                current = min(state['task_index'] + 1, len(state['tasks']))
                print(f"{state['elapsed_ms']:>6} ms  task {current}/{len(state['tasks'])}  "
                      f"{len(state['evidence'])} evidence items  {state['status']}")
        finally:
            trace = {**agent.snapshot(), **metadata,
                     "wall_elapsed_ms": round((time.perf_counter() - started) * 1000)}
            destination.write_text(json.dumps(trace, indent=2))
        if agent.result is not None:
            print(json.dumps(agent.result, indent=2))
        if agent.status != "done":
            raise SystemExit("Stopped without verified completion: " + str(agent.blocked_reason)
                             + "; inspect " + str(destination))


if __name__ == "__main__":
    raise SystemExit(main())
