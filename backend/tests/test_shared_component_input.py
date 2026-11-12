"""R129 source preparation must be immutable before sharing across targets."""
from copy import deepcopy
from dataclasses import replace

import pytest

from tests.test_component_incremental import component, engine, apply


def referenced_input():
    return replace(component(0),extra={'source_ref':{
        'series':'qualified-source','revision':1,'proof':{'rows':[1]}}})


def test_component_snapshot_nested_reference_is_readonly_in_published_copy():
    executor = engine()
    value = referenced_input()
    state, _ = apply(executor,value)
    snapshot = deepcopy(state)
    ref = snapshot.source_snapshots[value.input_key]['source_ref']
    with pytest.raises(TypeError):
        ref['revision'] = 9
    with pytest.raises((AttributeError,TypeError)):
        ref['proof']['rows'].append(2)
    assert state.source_snapshots[value.input_key]['source_ref']['revision'] == 1


def test_accepted_reference_detaches_original_nested_input_payload():
    executor = engine()
    value = referenced_input()
    state, _ = apply(executor,value)
    value.extra['source_ref']['revision'] = 99
    value.extra['source_ref']['proof']['rows'].append(2)
    assert state.source_snapshots[value.input_key]['source_ref']['revision'] == 1
    assert tuple(state.source_snapshots[value.input_key]['source_ref']['proof']['rows']) == (1,)
    assert state.source_refs[value.input_key]['revision'] == 1
    assert state.source_refs[value.input_key]['proof']['rows'] == [1]


@pytest.mark.parametrize('closed',[False,True])
def test_replacement_reference_detaches_input_for_active_and_closed_owner(closed):
    executor = engine()
    first = referenced_input()
    state, _ = apply(executor,first)
    old = deepcopy(state)
    if closed:
        executor.close_bar(first.exchange,first.market_type,first.symbol,0)
    revised = replace(first,volume=.1,extra={'source_ref':{
        'series':'qualified-source','revision':2,'proof':{'rows':[2]}}})
    state, _ = apply(executor,revised)
    revised.extra['source_ref']['proof']['rows'].append(3)
    assert state.source_refs[first.input_key]['proof']['rows'] == [2]
    assert tuple(state.source_snapshots[first.input_key]['source_ref']['proof']['rows']) == (2,)
    assert old.source_refs[first.input_key]['proof']['rows'] == [1]


def test_cyclic_reference_rejected_before_changing_existing_owner():
    executor = engine()
    value = referenced_input()
    state, _ = apply(executor,value)
    before = deepcopy(state)
    ref = {'series':'qualified-source','revision':2}
    ref['proof'] = ref
    with pytest.raises(ValueError,match='cyclic'):
        apply(executor,replace(value,volume=9,extra={'source_ref':ref}))
    assert state.volume == before.volume
    assert state.source_snapshots == before.source_snapshots
    assert state.source_refs == before.source_refs
