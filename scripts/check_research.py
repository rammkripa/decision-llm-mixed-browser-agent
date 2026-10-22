"""Real local browser + deterministic model doubles. No credentials or paid calls.

The fixture-specific policy below is test scaffolding, never the production policy.
"""

import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from jev_ultrafast import ResearchAgent, model, research

STATIC = Path(__file__).resolve().parents[1] / "jev_ultrafast" / "static"
GOAL = "Compare Basic and Pro annual costs for five seats, cancellation deadlines and refund exceptions."
TASK = {"objective": GOAL, "requirements": ["Five-seat annual quote, taxes, cancellation and refund exceptions"]}


def main():
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(STATIC))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    completed = set()

    def choose(page, *_args, **_kwargs):
        actions = page["actions"]
        selected = None
        if "seats" not in completed:
            selected = next(a for a in actions if a["kind"] == "fill")
            completed.add("seats")
        elif "calculate" not in completed:
            selected = next(a for a in actions if a["kind"] == "click" and "Calculate" in a["label"])
            completed.add("calculate")
        else:
            for key, text in [("quote", "Annual quote for 5 seats"),
                              ("cancel", "30 days before renewal"), ("refund", "duplicate charge")]:
                if key not in completed:
                    selected = next((a for a in actions if a["kind"] == "read" and text in a["label"]), None)
                    if selected:
                        completed.add(key)
                        break
            if selected is None and "policy" not in completed:
                selected = next(a for a in actions if a["kind"] == "click" and "Cancellation" in a["label"])
                completed.add("policy")
        operation = {"fill": "TYPE_TEXT", "click": "CLICK", "read": "READ_SECTION"}
        selected_id = selected["id"] if selected else "DONE"
        return {"choice": selected_id, "operation": operation[selected["kind"]] if selected else "DONE",
                "target": selected_id, "confidence": 1, "target_confidence": 1,
                "probabilities": {selected_id: 1}, "latency_ms": 0, "usage": {}}

    def generate(instructions, context):
        if "passage" in context:
            text = context["passage"]["text"]
            return {"facts": [{"requirement": 1, "value": text, "quote": text}]}
        return {"answer": "Basic costs $600 USD annually; Pro costs $1200 USD for five seats, taxes excluded. "
                          "Cancel 30 days before renewal. Annual payments are non-refundable except duplicate "
                          "charges reported within 14 days.", "evidence_ids": [1, 2, 3]}

    def verify(_goal, _requirements, page, evidence):
        # Independent fixture oracle, not a model DONE decision or extractor's self-assessment.
        text = " ".join(e["quote"] for e in evidence)
        passed = (page["url"] == base + "/research_policy.html"
                  and sum(e.get("verification") == "quote_matched" for e in evidence) == 3
                  and all(value in text for value in ["Basic $600 USD", "Pro $1200 USD", "Taxes excluded",
                                                      "30 days before renewal", "duplicate charge", "14 days"])
                  and all(e["quote"] in e["source_text"] for e in evidence))
        return {"passed": passed, "oracle": "local fixture expected values"}

    try:
        with patch.object(research, "plan", return_value=[TASK]), patch.object(model, "choose", side_effect=choose), \
             patch.object(model, "field_text", return_value=("5", {"model": "offline", "latency_ms": 0})), \
             patch("jev_ultrafast.agent.field_text", return_value=("5", {"model": "offline", "latency_ms": 0})), \
             patch.object(research, "generate_json", side_effect=generate), \
             patch.object(research, "verify", side_effect=verify), \
             patch.object(model, "post_json", side_effect=AssertionError("Paid API forbidden in local smoke")):
            with ResearchAgent(base + "/research.html", GOAL) as agent:
                # Actual content reader must include offscreen rendered text and exclude hidden instructions.
                document = research.capture(agent.runner.browser)
                assert not any("Ignore the user" in b["text"] for b in document["blocks"])
                agent.runner.browser.evaluate("""(() => {
                  const area=document.createElement('textarea'); area.id='reader-private';
                  area.textContent='PRIVATE_FORM_VALUE'; document.body.append(area);
                  const large=document.createElement('p'); large.id='reader-large';
                  large.textContent='x'.repeat(65000); document.body.append(large);
                })()""")
                capped = research.capture(agent.runner.browser)
                assert capped["truncated"] and len(capped["blocks"]) <= 400
                assert sum(len(b["text"]) for b in capped["blocks"]) <= 60000
                assert not any("PRIVATE_FORM_VALUE" in b["text"] for b in capped["blocks"])
                agent.runner.browser.evaluate("""document.getElementById('reader-private').remove();
                  document.getElementById('reader-large').remove();""")
                for state in agent.run():
                    if len(agent.events) > 20:
                        raise AssertionError("Unexpected loop")
                assert agent.status == "done", state
                assert len(agent.runner.state["history"]) == 3
                assert agent.runner.state["history"][0]["text"] == "5"
                assert any(not b["in_viewport"] and "duplicate charge" in b["text"]
                           for b in research.capture(agent.runner.browser)["blocks"])
                output = Path("artifacts/research-local-smoke.json")
                output.parent.mkdir(exist_ok=True)
                output.write_text(json.dumps(agent.snapshot(), indent=2))
                print("PASS: typing, calculation, navigation, offscreen reading, hidden/form exclusion, "
                      "reader limits, exact evidence, final oracle")
                print(output)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
