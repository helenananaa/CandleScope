"""Persisted alert fences must survive async calculation and history pruning."""
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.alerts.store import AlertStore


def rule(store):
    return store.upsert_rule({'id': 'r', 'name': 'RSI',
        'target': {'symbol': 'BTCUSDT', 'interval': '1m'},
        'expression': {'left': 'rsi', 'comparator': '>', 'right': {'type': 'number', 'value': 50}},
        'afterTrigger': 'keep', 'cooldownMs': 0})


def event(definition, bar=120, *, event_id=None):
    return {'id': event_id or f'{definition}:{bar}', 'ruleId': 'r', 'expectedDefinitionRevision': definition,
            'evaluationCursor': {'barTime': bar, 'observationTime': 0, 'ordinal': 0}}


def test_definition_survives_triggers_but_actions_and_aba_edits_fence_old_work(tmp_path):
    store = AlertStore(tmp_path / 'alerts.json')
    first = rule(store)
    revision = first['definitionRevision']
    assert store.append_history_if_eligible(event(revision))
    assert store.get_rule('r')['definitionRevision'] == revision
    changed = store.upsert_rule({'id': 'r', 'actions': [{'type': 'sound'}]})
    assert changed['definitionRevision'] != revision
    assert changed['triggerCount'] == 1  # Action edits do not rearm lifecycle counts.
    restored = store.upsert_rule({'id': 'r', 'actions': first['actions']})
    assert restored['definitionRevision'] not in (revision, changed['definitionRevision'])
    assert store.append_history_if_eligible(event(revision, 180)) is None
    assert store.append_history_if_eligible(event(restored['definitionRevision'], 180))


def test_cursor_survives_history_pruning_and_process_restart(tmp_path):
    path = tmp_path / 'alerts.json'
    store = AlertStore(path)
    revision = rule(store)['definitionRevision']
    assert store.append_history_if_eligible(event(revision, 120))
    # Retention may remove every trigger ID. It cannot remove the rule fence.
    data = store._load()
    data['history'] = []
    store._save(data)
    restarted = AlertStore(path)
    assert restarted.append_history_if_eligible(event(revision, 120, event_id='redelivery')) is None
    assert restarted.append_history_if_eligible(event(revision, 60, event_id='older')) is None
    assert restarted.append_history_if_eligible(event(revision, 180, event_id='new'))
    assert restarted.get_rule('r')['triggerCount'] == 2


def test_reenable_has_new_definition_and_new_cursor_without_old_count(tmp_path):
    store = AlertStore(tmp_path / 'alerts.json')
    revision = rule(store)['definitionRevision']
    assert store.append_history_if_eligible(event(revision))
    store.set_enabled('r', False)
    enabled = store.set_enabled('r', True)
    assert enabled['definitionRevision'] != revision
    assert enabled['triggerCount'] == 0
    assert store.append_history_if_eligible(event(revision, 180)) is None
    assert store.append_history_if_eligible(event(enabled['definitionRevision'], 180))


def test_definition_and_cursor_are_checked_in_the_same_store_commit(tmp_path):
    store = AlertStore(tmp_path / 'alerts.json')
    revision = rule(store)['definitionRevision']
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: store.append_history_if_eligible(
            event(revision, event_id=f'copy-{n}')), range(8)))
    assert sum(result is not None for result in results) == 1
    assert store.get_rule('r')['triggerCount'] == 1


@pytest.mark.parametrize('cursor', [None, {}, {'barTime': 0, 'observationTime': -1, 'ordinal': 0},
    {'barTime': True, 'observationTime': 1, 'ordinal': 0}])
def test_invalid_cursor_cannot_commit_a_fenced_evaluation(tmp_path, cursor):
    store = AlertStore(tmp_path / 'alerts.json')
    revision = rule(store)['definitionRevision']
    value = event(revision)
    value['evaluationCursor'] = cursor
    assert store.append_history_if_eligible(value) is None
    assert store.get_rule('r')['triggerCount'] == 0


def test_legacy_definition_is_stable_and_noop_edits_preserve_cursor(tmp_path):
    import json
    path = tmp_path / 'alerts.json'
    store = AlertStore(path)
    rule(store)
    data = json.loads(path.read_text())
    data['rules'][0].pop('definitionRevision')
    path.write_text(json.dumps(data))
    first = AlertStore(path).get_rule('r')['definitionRevision']
    assert first.startswith('legacy:')
    assert AlertStore(path).get_rule('r')['definitionRevision'] == first
    assert store.append_history_if_eligible(event(first))
    unchanged = store.upsert_rule({'id': 'r', 'name': 'RSI'})
    assert unchanged['definitionRevision'] == first
    assert unchanged['triggerCount'] == 1
    assert store.append_history_if_eligible(event(first, event_id='duplicate')) is None
