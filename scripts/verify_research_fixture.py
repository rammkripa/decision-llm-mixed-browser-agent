"""Independent expected outcomes for the research fixture. No browser or paid APIs."""

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse


def verify_fixture(trace):
    history = trace.get("history", [])
    evidence = trace.get("evidence", [])
    answer = (trace.get("result") or {}).get("answer", "").lower().replace(",", "")
    quotes = " ".join(e.get("quote", "") for e in evidence)
    sources = (trace.get("result") or {}).get("sources", [])
    checks = {
        "agent_completed": trace.get("status") == "done",
        "five_seats_entered": any(h.get("kind") == "fill" and h.get("text") == "5" for h in history),
        "calculator_submitted": any(h.get("action") == "Calculate annual costs" for h in history),
        "policy_visited": any(urlparse(h.get("url", "")).path == "/research_policy.html" for h in history),
        "known_prices_and_conditions": all(value in quotes for value in [
            "Basic $600 USD", "Pro $1200 USD", "Taxes excluded", "30 days", "duplicate charge", "14 days"]),
        "exact_quotes": bool(evidence) and all(e.get("quote") and e["quote"] in e.get("source_text", "")
                                               for e in evidence),
        "answer_covers_required_values": all(value in answer for value in ["600", "1200", "tax", "30", "14"])
        and "duplicate" in answer and "refund" in answer and "exclud" in answer
        and bool(re.search(r"basic[^.!?;\n]{0,60}600\b|600\s*(?:usd\s*)?for basic", answer))
        and bool(re.search(r"pro[^.!?;\n]{0,60}1200\b|1200\s*(?:usd\s*)?for pro", answer)),
        "answer_has_real_source_references": bool(sources) and all(
            type(s.get("id")) is int and 1 <= s["id"] <= len(evidence)
            and all(s.get(k) == evidence[s["id"] - 1].get(k) for k in ("url", "quote", "title")) for s in sources),
    }
    return {"passed": all(checks.values()), "checks": checks}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    result = verify_fixture(json.loads(args.trace.read_text()))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
