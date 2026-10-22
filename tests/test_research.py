"""Hybrid planning/reading contracts. Every model and browser dependency is offline."""

import json
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
    monkeypatch.setattr(research, "resolve_target", lambda *_: None)
    monkeypatch.setattr(research, "resolve_operation", lambda *_: None)
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
    agent.max_answer_attempts = 1
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
                                    "verification": 3, "synthesis": 1, "typing": 0,
                                    "target_resolution": 0, "verification_review": 0, "decision_resolution": 0}


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


def test_large_documents_are_paged_without_losing_passages(monkeypatch, hybrid):
    document = deepcopy(DOCUMENT)
    document['blocks'] = [{'id': str(i), 'text': f'Passage {i}'} for i in range(1, 401)]
    monkeypatch.setattr(research, 'capture', lambda _: deepcopy(document))
    offered = []

    def choose(observation, goal, *_args, **_kwargs):
        reads = [a for a in observation['actions'] if a['kind'] == 'read']
        assert len(reads) <= model.MAX_CHOICES
        offered.extend(a['id'] for a in reads)
        selected = 'read_next' if len(offered) == 200 else 'read_previous'
        assert selected in {a['id'] for a in observation['actions']}
        return {**decision(selected), 'operation': selected.upper()}

    monkeypatch.setattr(model, 'choose', choose)
    hybrid.tick()
    hybrid.tick()
    assert offered == [f'read_{i}' for i in range(1, 401)]
    assert hybrid.content_offsets[document['snapshot_id']] == 0
    hybrid.runner.command.assert_not_called()


def test_oversized_choice_head_fails_before_network(monkeypatch):
    post = Mock()
    monkeypatch.setattr(model, 'post_json', post)
    observed = page()
    observed['actions'] += [{'id': f'read_{i}', 'kind': 'read', 'node': f'content_{i}',
                             'label': 'Observed text', 'role': 'passage'} for i in range(256)]
    with pytest.raises(ValueError, match='TypeSafe allows at most 255'):
        model.choose(observed, 'Read', [])
    post.assert_not_called()


def test_validation_error_shows_location_without_echoing_input():
    import httpx

    response = httpx.Response(422, json={'detail': [{
        'loc': ['body', 'questions', 'read_section_target', 'criteria'],
        'msg': 'At most 255 choices; private-key', 'input': 'PRIVATE_PAGE_CONTENT'}]})
    message = model.provider_error(response, 'private-key')
    assert 'body.questions.read_section_target.criteria' in message
    assert '255' in message and '[redacted]' in message
    assert 'PRIVATE_PAGE_CONTENT' not in message and 'private-key' not in message


def test_target_resolver_can_only_select_observed_compatible_target(monkeypatch):
    d = {**decision('e2'), 'operation': 'CLICK', 'target': '1',
         'target_probabilities': {'1': .6, '2': .4}}
    monkeypatch.setattr(research, 'generate_json', lambda *_: {'target': '2'})
    result = research.resolve_target('Search', page(), d, [])
    assert result['choice'] == 'e3' and result['target'] == '2'
    assert result['target_resolution']['original_target'] == '1'
    monkeypatch.setattr(research, 'generate_json', lambda *_: {'target': '#invented-selector'})
    with pytest.raises(ValueError, match='unobserved target'):
        research.resolve_target('Search', page(), d, [])


def test_target_tie_breaker_keeps_raw_distribution_and_uses_existing_executor(monkeypatch, hybrid):
    raw = {**decision('e2'), 'operation': 'CLICK', 'confidence': .95, 'target_confidence': .5}
    monkeypatch.setattr(model, 'choose', lambda *_args, **_kwargs: raw)
    resolved = {**raw, 'choice': 'e3', 'target_resolution': {'method': 'text_model'}}
    monkeypatch.setattr(research, 'resolve_target', lambda *_: resolved)
    hybrid.tick()
    assert hybrid.model_calls['target_resolution'] == 1
    assert hybrid.runner.state['decision']['choice'] == 'e3'
    assert hybrid.events[-1]['decision'] is raw
    assert hybrid.events[-1]['resolved_decision']['target_confidence'] == .5
    hybrid.runner.command.assert_called_once()


def test_quote_across_captured_inline_fragments_preserves_observed_text():
    blocks = [{'id': '1', 'text': 'A consistent formal system'},
              {'id': '2', 'text': 'cannot prove its own consistency.'}]
    source, quote = research.resolve_quote('A consistent formal system cannot prove its own consistency.', blocks)
    assert source['id'] == 'context:1,2'
    assert quote == 'A consistent formal system\ncannot prove its own consistency.'
    assert quote in source['text']


def test_invalid_extraction_retries_generation_once_without_browser_mutation(monkeypatch, hybrid):
    set_decision(monkeypatch, 'READ_SECTION', 'read_1')
    generate = Mock(side_effect=[{'facts': [{**FACT, 'quote': 'Invented quote'}]}, {'facts': [FACT]}])
    monkeypatch.setattr(research, 'generate_json', generate)
    hybrid.tick()
    assert hybrid.model_calls['extraction'] == 2
    assert hybrid.events[-1]['extraction_retried']
    assert len(hybrid.evidence) == 1
    hybrid.runner.command.assert_not_called()


def test_content_windows_bound_text_and_preserve_every_passage():
    blocks = [{'id': str(i), 'text': 'x' * 2000} for i in range(7)]
    windows = research.content_windows(blocks)
    assert [offset for offset, _ in windows] == [0, 3, 6]
    assert [block for _, window in windows for block in window] == blocks
    assert all(sum(len(b['text']) for b in window) <= research.CONTENT_WINDOW_CHARS for _, window in windows)


def test_shared_goal_is_sent_once_across_speculative_heads(monkeypatch):
    goal = 'UNIQUE_GOAL_SENTINEL'
    captured = []
    def post(_url, _key, body):
        captured.append(body)
        return {'model': 'offline', 'answers': {
            'operation': choice(body['questions']['operation']['criteria'], 'DONE')}}
    monkeypatch.setenv('TYPESAFE_API_KEY', 'offline')
    monkeypatch.setattr(model, 'post_json', post)
    model.choose(page(), goal, [])
    assert json.dumps(captured[0]).count(goal) == 1
    assert captured[0]['state']['goal'] == goal


def test_verification_deduplicates_shared_source_context(monkeypatch):
    captured = []
    def post(_url, _key, body):
        captured.append(body)
        return {'answers': {'0': choice(['supported', 'missing'], 'supported')}}
    monkeypatch.setenv('TYPESAFE_API_KEY', 'offline')
    monkeypatch.setattr(model, 'post_json', post)
    facts = [{**FACT, 'url': 'https://example.test', 'context_text': 'One shared source.'} for _ in range(2)]
    research.verify('Get facts', ['A requirement'], page(), facts)
    assert len(captured[0]['state']['sources']) == 1
    assert [e['source'] for e in captured[0]['state']['evidence']] == [0, 0]


def test_extractor_selects_code_owned_quote_without_copying_text(monkeypatch):
    fact = {'requirement': 1, 'value': 'Five seats cost $600 annually.', 'quote_id': '1'}
    monkeypatch.setattr(research, 'generate_json', lambda *_: {'facts': [fact]})
    evidence = research.extract(TASK, DOCUMENT['blocks'][0], DOCUMENT)[0]
    assert evidence['quote'] == DOCUMENT['blocks'][0]['text']
    assert evidence['source_text'] == evidence['quote']
    monkeypatch.setattr(research, 'generate_json', lambda *_: {'facts': [{**fact, 'quote_id': 'invented'}]})
    with pytest.raises(ValueError, match='unobserved quote_id'):
        research.extract(TASK, DOCUMENT['blocks'][0], DOCUMENT)


def test_uncertain_verification_routes_to_source_witnessed_review(monkeypatch, hybrid):
    uncertain = {'passed': False, 'checks': [
        {'choice': 'supported', 'probabilities': {'supported': .75, 'missing': .25}, 'confidence': .5}]}
    monkeypatch.setattr(research, 'verify', lambda *_: uncertain)
    monkeypatch.setattr(research, 'generate_json', lambda *_: {
        'checks': [{'requirement': 1, 'supported': True, 'source_ids': ['1']}]})
    result = hybrid.check(['Observed fact'], page(), [])
    assert result['passed'] and not result['jev_passed']
    assert hybrid.model_calls['verification_review'] == 1
    assert result['text_review']['sources']['1']['source_text'] == page()['text']


def test_requirement_review_rejects_invented_source(monkeypatch):
    monkeypatch.setattr(research, 'generate_json', lambda *_: {
        'checks': [{'requirement': 1, 'supported': True, 'source_ids': ['invented']}]})
    with pytest.raises(ValueError, match='unobserved source'):
        research.review_requirements('Read', ['A fact'], page(), [])


def test_confidently_missing_requirement_is_not_overridden(monkeypatch, hybrid):
    monkeypatch.setattr(research, 'verify', lambda *_: {'passed': False, 'checks': [
        {'choice': 'missing', 'confidence': .95, 'probabilities': {'supported': .02, 'missing': .98}}]})
    reviewer = Mock()
    monkeypatch.setattr(research, 'review_requirements', reviewer)
    assert not hybrid.check(['Missing fact'], page(), [])['passed']
    reviewer.assert_not_called()


def test_operation_fallback_never_consumes_another_operations_target(monkeypatch):
    raw = {**decision('e2'), 'operation': 'CLICK'}
    monkeypatch.setattr(research, 'generate_json', lambda *_: {'operation': 'TYPE_TEXT', 'target': '2'})
    with pytest.raises(ValueError, match='unobserved target'):
        research.resolve_operation('Search', page(), raw, [])
    monkeypatch.setattr(research, 'generate_json', lambda *_: {'operation': 'CLICK', 'target': '2'})
    resolved = research.resolve_operation('Search', page(), raw, [])
    assert resolved['choice'] == 'e3' and resolved['confidence'] is None
    assert resolved['probabilities'] == {'e3': None}
    monkeypatch.setattr(research, 'generate_json', lambda *_: {'operation': 'WAIT', 'target': '1'})
    with pytest.raises(ValueError, match='targetless operation'):
        research.resolve_operation('Search', page(), raw, [])


def test_answer_revision_is_bounded_and_never_repeats_browser_mutations(monkeypatch, hybrid):
    hybrid.max_answer_attempts = 2
    monkeypatch.setattr(hybrid, 'repair_citations', Mock(side_effect=ValueError('No supporting citations')))
    set_decision(monkeypatch, 'DONE', 'DONE')
    checker = Mock(side_effect=[{'passed': True}, {'passed': True}, {'passed': False},
                               {'passed': True}, {'passed': True}])
    monkeypatch.setattr(research, 'verify', checker)
    monkeypatch.setattr(research, 'generate_json', Mock(side_effect=[
        {'answer': 'Unsupported wording.', 'evidence_ids': []},
        {'answer': 'Supported wording.', 'evidence_ids': []}]))
    hybrid.tick()
    assert hybrid.status == 'done' and hybrid.result['answer'] == 'Supported wording.'
    assert len(hybrid.answer_attempts) == 2
    assert hybrid.model_calls['synthesis'] == 2
    hybrid.runner.command.assert_not_called()


@pytest.mark.parametrize('resume', [True, False])
def test_captcha_handoff_precedes_models_and_mutations(monkeypatch, hybrid, resume):
    challenge = {**page(), 'text': 'Our systems have detected unusual traffic from your computer network.'}
    hybrid.runner.browser.observe.return_value = challenge
    handler = Mock(return_value=resume)
    hybrid.human_handoff = handler
    choose = Mock()
    capture = Mock()
    monkeypatch.setattr(model, 'choose', choose)
    monkeypatch.setattr(research, 'capture', capture)
    hybrid.runner.state['decision'] = {'choice': 'old'}
    hybrid.runner.pending_text = ('old', 'text')
    result = hybrid.tick()
    assert result['status'] == ('ready' if resume else 'blocked')
    handler.assert_called_once_with(challenge)
    choose.assert_not_called()
    capture.assert_not_called()
    hybrid.runner.command.assert_not_called()
    assert hybrid.runner.state['decision'] is None
    assert hybrid.runner.pending_text is None
    assert hybrid.events[-1]['resumed'] is resume
    if resume:
        # A second tick must use the new page rather than replaying a saved action.
        hybrid.runner.browser.observe.return_value = page()
        capture.side_effect = StalePage('Fresh observation')
        hybrid.tick()
        assert hybrid.runner.browser.observe.call_count == 2
        capture.assert_called_once()


def test_regular_page_does_not_require_human_verification():
    assert not research.needs_human_verification(page())


def test_invalid_operation_resolution_is_rejected_without_crashing(monkeypatch, hybrid):
    set_decision(monkeypatch, 'WAIT', 'wait', confidence=.39)
    resolver = Mock(side_effect=ValueError('Operation resolver returned an unobserved target'))
    monkeypatch.setattr(research, 'resolve_operation', resolver)
    result = hybrid.tick()
    assert result['status'] == 'ready'
    assert hybrid.events[-1]['status'] == 'uncertain'
    assert 'unobserved target' in hybrid.events[-1]['resolution_error']
    hybrid.runner.command.assert_not_called()
    # Repeated invalid generations stop under the existing recovery budget.
    hybrid.tick()
    result = hybrid.tick()
    assert result['status'] == 'blocked'
    assert resolver.call_count == 3
    hybrid.runner.command.assert_not_called()


@pytest.mark.parametrize('remaining_goal_passes', [True, False])
def test_suppression_after_revision_rechecks_remaining_goal(monkeypatch, hybrid, remaining_goal_passes):
    hybrid.max_answer_attempts = 2
    verdict = {'passed': False, 'checks': [choice(['supported', 'missing'], 'supported'),
                                          choice(['supported', 'missing'], 'missing')]}
    checker = Mock(side_effect=[{'passed': True}, verdict, {'passed': True}, verdict,
                                {'passed': True}, {'passed': remaining_goal_passes}])
    monkeypatch.setattr(hybrid, 'check', checker)
    writer = Mock(return_value={'answer': 'Flight costs $62. Airports are unavailable.', 'evidence_ids': []})
    monkeypatch.setattr(research, 'generate_json', writer)
    hybrid.finish_goal(hybrid.runner.state['page'])
    assert writer.call_count == 2
    assert checker.call_args_list[-2].args[0] == ['Flight costs $62.']
    assert checker.call_args_list[-1].args[1]['candidate_answer'] == 'Flight costs $62.'
    assert hybrid.answer_attempts[-1]['suppressed_statements'] == ['Airports are unavailable.']
    if remaining_goal_passes:
        assert hybrid.status == 'done'
        assert hybrid.result['answer'] == 'Flight costs $62.'
    else:
        assert hybrid.status == 'blocked'
        assert hybrid.result is None
    hybrid.runner.command.assert_not_called()


def test_statement_filter_uses_indexed_review_over_raw_choices():
    check = {'checks': [choice(['supported', 'missing'], 'supported')] * 2,
             'text_review': {'checks': [{'requirement': 2, 'supported': True},
                                        {'requirement': 1, 'supported': False}]}}
    assert research.supported_statement_indices(check, 2) == {1}
    assert research.supported_statement_indices(check, 3) == set()


def test_citation_repair_recovers_uncited_evidence_without_rewriting(monkeypatch, hybrid):
    hybrid.evidence = [dict(FACT, url='https://example.test', title='Source', observed_at='now')] * 2
    monkeypatch.setattr(research, 'generate_json', Mock(side_effect=[
        {'answer': 'Launch date is known. L2 keeps Webb cold. [1]', 'evidence_ids': [1]},
        {'citations': [{'statement': 1, 'evidence_ids': [1]}, {'statement': 2, 'evidence_ids': [2]}]},
    ]))
    checker = Mock(side_effect=[{'passed': True}, {'passed': False}, {'passed': True}])
    monkeypatch.setattr(hybrid, 'check', checker)
    hybrid.finish_goal(hybrid.runner.state['page'])
    assert hybrid.status == 'done'
    assert hybrid.result['evidence_ids'] == [1, 2]
    assert hybrid.result['answer'] == 'Launch date is known. [1]\nL2 keeps Webb cold. [2]'
    assert hybrid.model_calls['citation_repair'] == 1
    hybrid.runner.command.assert_not_called()


def test_citation_repair_rejects_invented_reference(monkeypatch, hybrid):
    hybrid.evidence = [FACT]
    monkeypatch.setattr(research, 'generate_json', lambda *_: {
        'citations': [{'statement': 1, 'evidence_ids': [999]}]})
    with pytest.raises(ValueError, match='unobserved evidence'):
        hybrid.repair_citations(['A claim.'], [])


def test_read_consumes_whole_extraction_window(monkeypatch, hybrid):
    document = deepcopy(DOCUMENT)
    document['blocks'].append({'id': '2', 'text': 'More information.', 'tag': 'p'})
    monkeypatch.setattr(research, 'capture', lambda _: document)
    monkeypatch.setattr(research, 'generate_json', lambda *_: {'facts': [FACT]})
    set_decision(monkeypatch, 'READ_SECTION', 'read_1')
    hybrid.tick()
    assert hybrid.events[-1]['inspected_passages'] == ['1', '2']
    assert (0, 0, 'snapshot-1', '2') in hybrid.read
    # A re-read with the same facts cannot inflate the evidence store.
    hybrid.read.clear()
    hybrid.tick()
    assert len(hybrid.evidence) == 1
    assert hybrid.events[-1]['new_evidence'] == 0


def test_decision_evidence_is_bounded_without_discarding_stored_sources():
    evidence = [{'value': 'x' * 5000, 'quote': 'y' * 5000, 'url': 'https://example.test'}] * 100
    compact = research.decision_evidence(evidence, limit=6000)
    assert len(json.dumps(compact)) < 6100
    assert len(evidence) == 100
    assert len(evidence[0]['value']) == 5000
