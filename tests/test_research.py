"""Hybrid planning/reading contracts. Every model and browser dependency is offline."""

from copy import deepcopy
from unittest.mock import Mock

import pytest
from test_agent import choice, decision, page

from jev_ultrafast import model, research
from jev_ultrafast.browser import StalePage

TASK = {"objective": "Find annual cost", "requirements": ["Annual cost for five seats including conditions"]}
DOCUMENT = {"url": "https://example.test/", "title": "Pricing", "document_id": 1,
            "blocks": [{"id": "1", "text": "Five seats cost $600 annually. Taxes excluded.", "tag": "p"}],
            "truncated": False, "snapshot_id": "snapshot-1", "observed_at": "2026-10-22T00:00:00Z"}
FACT = {"requirement": 1, "value": "$600 annually; taxes excluded", "quote": DOCUMENT["blocks"][0]["text"]}


@pytest.mark.parametrize("tasks", [[], [{}], [{"objective": "X", "requirements": []}],
                                   [{"objective": "X", "requirements": [5]}], [TASK] * 9])
def test_invalid_plans_fail_before_opening_browser(monkeypatch, tasks):
    monkeypatch.setattr(research, "generate_json", lambda *_: {"tasks": tasks})
    browser_agent = Mock()
    monkeypatch.setattr(research, "Agent", browser_agent)
    with pytest.raises(ValueError):
        research.ResearchAgent("https://example.test", "Get prices")
    browser_agent.assert_not_called()


@pytest.mark.parametrize("change", [{"quote": "Free forever"}, {"requirement": 2}, {"requirement": True},
                                    {"value": ""}, {"selector": "body"}])
def test_fabricated_or_malformed_evidence_rejected(monkeypatch, change):
    monkeypatch.setattr(research, "generate_json", lambda *_: {"facts": [{**FACT, **change}]})
    with pytest.raises(ValueError):
        research.extract(TASK, DOCUMENT["blocks"][0], DOCUMENT)


def test_evidence_preserves_immutable_source_and_provenance(monkeypatch):
    monkeypatch.setattr(research, "generate_json", lambda *_: {"facts": [FACT]})
    facts = research.extract(TASK, DOCUMENT["blocks"][0], DOCUMENT)
    assert facts[0]["snapshot_id"] == "snapshot-1"
    assert facts[0]["source_text"] == facts[0]["quote"]
    assert facts[0]["verification"] == "quote_matched"


def test_read_heads_are_batched_and_unused_click_head_ignored(monkeypatch):
    calls = []

    def post(_url, _key, body):
        calls.append(body)
        return {"model": "test", "answers": {
            "operation": choice(body["questions"]["operation"]["criteria"], "READ_SECTION"),
            "read_section_target": choice(["3"], "3"), "click_target": {"choice": "invented"}}}

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    observed = page()
    observed["actions"].append({"id": "read_1", "kind": "read", "node": "content_1",
                                "role": "passage", "label": "Costs", "value": ""})
    result = model.choose(observed, "Find costs", [])
    assert result["choice"] == "read_1"
    assert len(calls) == 1
    assert "read_section_target" in calls[0]["questions"]


@pytest.fixture
def hybrid(monkeypatch):
    monkeypatch.setattr(research, "plan", lambda _: [deepcopy(TASK)])
    monkeypatch.setattr(research, "verify", lambda *_: {"passed": False, "checks": []})
    monkeypatch.setattr(research, "generate_json", lambda *_: {"answer": "Observed outcome", "evidence_ids": []})
    observed = page()
    observed["marker"] = [1]
    browser = Mock()
    browser.observe.return_value = observed
    runner = Mock()
    runner.browser = browser
    runner.state = {"page": observed, "history": [], "started_at": None, "decisions": [],
                    "status": "ready", "goal": "", "elapsed_ms": 0}
    runner.snapshot.side_effect = lambda: dict(runner.state, browser=None)
    monkeypatch.setattr(research, "Agent", lambda *_: runner)
    monkeypatch.setattr(research, "capture", lambda _: deepcopy(DOCUMENT))
    agent = research.ResearchAgent("https://example.test/", "Find annual cost for five seats", max_replans=0)
    return agent


def set_decision(monkeypatch, operation, selected, confidence=1):
    result = {**decision(selected), "operation": operation, "confidence": confidence,
              "target_confidence": confidence}
    monkeypatch.setattr(model, "choose", lambda *_args, **_kwargs: result)


def test_read_is_not_browser_mutation_and_not_offered_twice(monkeypatch, hybrid):
    set_decision(monkeypatch, "READ_SECTION", "read_1")
    monkeypatch.setattr(research, "generate_json", lambda *_: {"facts": [FACT]})
    hybrid.tick()
    hybrid.runner.command.assert_not_called()
    assert len(hybrid.evidence) == 1
    assert hybrid.events[-1]["status"] == "read"
    offered = []

    def next_choice(observed, *_args, **_kwargs):
        offered.extend(observed["actions"])
        return {**decision("BLOCKED"), "operation": "BLOCKED"}

    monkeypatch.setattr(model, "choose", next_choice)
    hybrid.tick()
    assert not any(a["kind"] == "read" for a in offered)


def test_done_without_evidence_does_not_finish(monkeypatch, hybrid):
    set_decision(monkeypatch, "DONE", "DONE")
    monkeypatch.setattr(research, "verify", lambda *_: {"passed": False, "checks": []})
    hybrid.tick()
    assert hybrid.status == "ready" and hybrid.index == 0
    assert hybrid.events[-1]["status"] == "incomplete"


def test_final_original_goal_check_catches_bad_plan(monkeypatch, hybrid):
    set_decision(monkeypatch, "DONE", "DONE")
    checker = Mock(side_effect=[{"passed": True}, {"passed": False}])
    monkeypatch.setattr(research, "verify", checker)
    hybrid.tick()
    assert hybrid.status == "blocked"
    assert checker.call_args.args[1] == [hybrid.goal]


def test_answer_requires_separate_support_check(monkeypatch, hybrid):
    set_decision(monkeypatch, "DONE", "DONE")
    monkeypatch.setattr(research, "verify", Mock(side_effect=[{"passed": True}, {"passed": True}, {"passed": False}]))
    monkeypatch.setattr(research, "generate_json", lambda *_: {"answer": "Unsupported conclusion", "evidence_ids": []})
    hybrid.tick()
    assert hybrid.status == "blocked"


def test_low_target_confidence_never_mutates(monkeypatch, hybrid):
    set_decision(monkeypatch, "CLICK", "e3", confidence=.1)
    for _ in range(3):
        hybrid.tick()
    assert hybrid.status == "blocked"
    hybrid.runner.command.assert_not_called()


def test_navigation_between_snapshots_discards_decision(monkeypatch, hybrid):
    document = {**DOCUMENT, "document_id": 2}
    monkeypatch.setattr(research, "capture", lambda _: document)
    chooser = Mock()
    monkeypatch.setattr(model, "choose", chooser)
    hybrid.tick()
    chooser.assert_not_called()
    hybrid.runner.command.assert_not_called()
    assert hybrid.events[-1]["status"] == "stale"


def test_execution_logged_even_when_next_observation_stale(monkeypatch, hybrid):
    set_decision(monkeypatch, "CLICK", "e3")

    def act(*_):
        hybrid.runner.state["history"].append({"action": "Go"})
        raise StalePage("Navigated after click")

    hybrid.runner.command.side_effect = act
    hybrid.tick()
    assert hybrid.events[0]["status"] == "executed"
    assert hybrid.runner.command.call_count == 1
    assert len(hybrid.runner.state["history"]) == 1


def test_verifier_rejects_confident_missing_and_uncertain_support(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    for answer in [choice(["supported", "missing"], "missing"),
                   {"choice": "supported", "confidence": .2, "probabilities": {"supported": .6, "missing": .4}}]:
        monkeypatch.setattr(model, "post_json", lambda *_: {"answers": {"0": answer}})
        assert not research.verify("Get costs", TASK["requirements"], page(), [FACT])["passed"]


def test_replanning_preserves_goal_evidence_and_mutation_history(monkeypatch, hybrid):
    hybrid.max_replans = 1
    hybrid.evidence = [{"value": "Known fact"}]
    hybrid.runner.state["history"] = [{"action": "Submitted form"}]
    hybrid.runner.pending_text = ("old context", "old value", {})
    replacement = {"objective": "Read missing exceptions", "requirements": ["Refund exception"]}
    planner = Mock(return_value=[replacement])
    monkeypatch.setattr(research, "plan", planner)
    set_decision(monkeypatch, "BLOCKED", "BLOCKED")
    hybrid.tick()
    assert hybrid.status == "ready" and hybrid.revision == 1
    assert hybrid.tasks == [replacement] and len(hybrid.plan_history) == 2
    context = planner.call_args.kwargs["context"]
    assert planner.call_args.args == (hybrid.goal,)
    assert context["evidence"] == hybrid.evidence
    assert context["recent_actions"] == [{"action": "Submitted form"}]
    assert hybrid.runner.pending_text is None
    hybrid.tick()
    assert hybrid.status == "blocked" and planner.call_count == 1
    hybrid.runner.command.assert_not_called()


def test_successful_completion_has_verified_result_and_call_counts(monkeypatch, hybrid):
    set_decision(monkeypatch, "DONE", "DONE")
    monkeypatch.setattr(research, "verify", lambda *_: {"passed": True})
    monkeypatch.setattr(research, "generate_json", lambda *_: {"answer": "Observed outcome", "evidence_ids": []})
    state = hybrid.tick()
    assert state["status"] == "done"
    assert state["result"]["answer"] == "Observed outcome"
    assert state["model_calls"] == {"planning": 1, "decision": 1, "extraction": 0,
                                    "verification": 3, "synthesis": 1, "typing": 0}


def test_rejected_answer_is_not_published(monkeypatch, hybrid):
    set_decision(monkeypatch, "DONE", "DONE")
    monkeypatch.setattr(research, "verify", Mock(side_effect=[{"passed": True}, {"passed": True}, {"passed": False}]))
    monkeypatch.setattr(research, "generate_json", lambda *_: {"answer": "Unfounded answer", "evidence_ids": []})
    hybrid.tick()
    assert hybrid.result is None
    assert "not supported" in hybrid.blocked_reason


def test_zero_target_confidence_cannot_fall_back_to_operation_confidence(monkeypatch, hybrid):
    value = {**decision("e3"), "operation": "CLICK", "confidence": 1, "target_confidence": 0}
    monkeypatch.setattr(model, "choose", lambda *_args, **_kwargs: value)
    hybrid.tick()
    assert hybrid.events[-1]["status"] == "uncertain"
    hybrid.runner.command.assert_not_called()


def test_repeated_failed_done_replans_instead_of_spinning(monkeypatch, hybrid):
    hybrid.max_replans = 1
    set_decision(monkeypatch, "DONE", "DONE")
    monkeypatch.setattr(research, "verify", lambda *_: {"passed": False})
    planner = Mock(return_value=[TASK])
    monkeypatch.setattr(research, "plan", planner)
    for _ in range(3):
        hybrid.tick()
    assert hybrid.revision == 1 and hybrid.failed_checks == 0
    assert planner.call_count == 1


@pytest.mark.parametrize("name,expected", [("gpt-6-luna", "none"), ("gpt-4.1-mini", None)])
def test_direct_openai_parameters_do_not_leak_openrouter_fields(monkeypatch, name, expected):
    monkeypatch.setenv("TEXT_MODEL_REASONING", "none")
    options = model.text_options("https://api.openai.com/v1", name, 1024)
    assert options["max_completion_tokens"] == 1024
    assert options.get("reasoning_effort") == expected
    assert "max_tokens" not in options and "reasoning" not in options and "thinking" not in options


def test_research_json_mode_explicitly_requests_json(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "offline-key")
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("TEXT_MODEL", "gpt-6-luna")
    post = Mock(return_value={"choices": [{"message": {"content": '{"facts":[]}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    assert research.generate_json('Return {"facts":[]}', {}) == {"facts": []}
    body = post.call_args.args[2]
    assert "json" in body["messages"][0]["content"].lower()
    assert body["max_completion_tokens"] == 4096


def test_quote_whitespace_resolution_preserves_observed_source():
    block = {"id": "2", "text": "Cancel at least 30 days before renewal\n to prevent the next charge."}
    source, quote = research.resolve_quote("30 days before renewal to prevent", [block])
    assert source is block
    assert quote == "30 days before renewal\n to prevent"
    assert quote in source["text"]
    with pytest.raises(ValueError):
        research.resolve_quote("30 days after renewal", [block])


def test_context_quote_maps_to_actual_observed_passage(monkeypatch):
    document = deepcopy(DOCUMENT)
    document['blocks'].append({'id': '2', 'text': 'No additional charges.'})
    fact = {"requirement": 1, "value": "No additional charges", "quote": "No additional charges."}
    monkeypatch.setattr(research, "generate_json", lambda *_: {"facts": [fact]})
    evidence = research.extract(TASK, document['blocks'][0], document)[0]
    assert evidence['passage_id'] == '2'
    assert evidence['source_text'] == 'No additional charges.'
    assert 'Five seats' in evidence['context_text']


def test_read_target_uncertainty_does_not_block_safe_information_gathering(monkeypatch, hybrid):
    result = {**decision("read_1"), "operation": "READ_SECTION", "confidence": .5, "target_confidence": .1}
    monkeypatch.setattr(model, "choose", lambda *_args, **_kwargs: result)
    monkeypatch.setattr(research, "generate_json", lambda *_: {"facts": []})
    hybrid.tick()
    assert hybrid.events[-1]["status"] == "read"
    hybrid.runner.command.assert_not_called()


def test_done_uncertainty_still_requires_independent_verification(monkeypatch, hybrid):
    set_decision(monkeypatch, "DONE", "DONE", confidence=.1)
    check = Mock(return_value={"passed": False})
    monkeypatch.setattr(research, "verify", check)
    hybrid.tick()
    assert check.call_count == 1 and hybrid.status == 'ready'


def test_extracted_evidence_can_advance_subtask_without_model_done(monkeypatch, hybrid):
    hybrid.tasks.append({"objective": "Read policy", "requirements": ["Cancellation deadline"]})
    set_decision(monkeypatch, "READ_SECTION", "read_1")
    monkeypatch.setattr(research, "generate_json", lambda *_: {"facts": [FACT]})
    monkeypatch.setattr(research, "verify", lambda *_: {"passed": True})
    hybrid.tick()
    assert hybrid.index == 1 and hybrid.status == "ready"
    assert len(hybrid.evidence) == 2
    assert hybrid.evidence[-1]["kind"] == "observed_outcome"
    hybrid.runner.command.assert_not_called()


def test_final_answer_checks_atomic_statements_and_retains_rejected_draft(monkeypatch, hybrid):
    set_decision(monkeypatch, "DONE", "DONE")
    checker = Mock(side_effect=[{"passed": True}, {"passed": True}, {"passed": False}])
    monkeypatch.setattr(research, "verify", checker)
    monkeypatch.setattr(research, "generate_json", lambda *_: {
        "answer": "Basic costs $600. Pro costs $1200.", "evidence_ids": []})
    hybrid.tick()
    assert checker.call_args.args[1] == ["Basic costs $600.", "Pro costs $1200."]
    assert hybrid.result is None and len(hybrid.answer_attempts) == 1
    assert not hybrid.answer_attempts[0]["verification"]["passed"]
