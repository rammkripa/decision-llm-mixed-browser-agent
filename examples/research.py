"""Run the hybrid agent; persist its complete trace locally, including on failure."""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from jev_ultrafast import ResearchAgent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--trace", default="artifacts/research.json")
    args = parser.parse_args()
    destination = Path(args.trace)
    destination.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    root = Path(__file__).resolve().parents[1]
    sources = ["jev_ultrafast/agent.py", "jev_ultrafast/model.py", "jev_ultrafast/research.py",
               "jev_ultrafast/browser.py", "jev_ultrafast/snapshot.js", "jev_ultrafast/content.js",
               "jev_ultrafast/static/research.html", "jev_ultrafast/static/research_policy.html"]
    metadata = {"models": {"decision": os.environ.get("TYPESAFE_MODEL", "jev-latest"),
                           "text": os.environ.get("TEXT_MODEL", "deepseek-chat")},
                "source_hashes": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources}}
    with ResearchAgent(args.url, args.goal) as agent:
        try:
            for state in agent.run():
                current = min(state['task_index'] + 1, len(state['tasks']))
                print(f"{state['elapsed_ms']:>6} ms  task {current}/{len(state['tasks'])}  "
                      f"{len(state['evidence'])} evidence items  {state['status']}")
        finally:
            trace = {**agent.snapshot(), **metadata,
                     "wall_elapsed_ms": round((time.perf_counter() - started) * 1000)}
            destination.write_text(json.dumps(trace, indent=2))
        print(json.dumps(agent.result, indent=2))
        if agent.status != "done":
            raise SystemExit("Stopped without verified completion; inspect " + str(destination))


if __name__ == "__main__":
    main()
