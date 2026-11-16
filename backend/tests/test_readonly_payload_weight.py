"""Immutable accepted-value weights are cached and include nested payloads."""
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction

import pytest

from app.data_engine import readonly
from app.data_engine.readonly import ReadonlyFields
from app.data_engine.memory_budget import retained_size


@pytest.mark.parametrize('values',[
    {}, {'x':1}, {'x':None,'y':True,'z':False},
    {'text':'x'*8192,'binary':b'y'*1024},
    {'source_ref':{'series':'source','revision':10,'proof':{'text':'a'*8192}}},
    {'items':[{'a':1},('b',{'c':b'd'*256}),frozenset({1,2,3})]},
    {'decimal':Decimal('10.002'),'fraction':Fraction(1,3)},
])
def test_record_weight_covers_accepted_python_values(values):
    record=ReadonlyFields(values)
    assert record.estimated_bytes>=retained_size([record])[0]
    assert deepcopy(record) is record
    with pytest.raises(TypeError):record._estimated_bytes=0


def test_weights_are_cached_and_external_changes_do_not_change_accepted_values(monkeypatch):
    raw={'source_ref':{'proof':['original',{'text':'x'*8192}]}}
    record=ReadonlyFields(raw);before=record.estimated_bytes
    raw['source_ref']['proof'][1]['text']='changed'
    raw['source_ref']['proof'].clear()
    def forbidden(*args):raise AssertionError('repeated field-weight traversal')
    monkeypatch.setattr(readonly,'frozen_reference_weight',forbidden)
    assert record.estimated_bytes==before
    assert record['source_ref'].estimated_bytes>8192
    assert record['source_ref']['proof'][1]['text']=='x'*8192


def test_nested_readonly_values_reuse_cached_weights_without_deep_rescan(monkeypatch):
    inner=ReadonlyFields({'payload':'x'*8192})
    original=readonly.frozen_reference_weight;visited=[]
    def count(value):
        visited.append(value)
        return original(value)
    monkeypatch.setattr(readonly,'frozen_reference_weight',count)
    outer=ReadonlyFields({'nested':inner})
    assert outer['nested'] is inner
    assert not any(value is inner['payload'] for value in visited)
    assert outer.estimated_bytes>=retained_size([outer])[0]


def test_heap_diagnostic_includes_real_proxy_and_retained_weight_counter():
    import sys
    record=ReadonlyFields({})
    expected=(sys.getsizeof(record)+sys.getsizeof(record._values)
              +sys.getsizeof({})+sys.getsizeof(record._estimated_bytes))
    assert retained_size([record])[0]==expected
    # Shared direct/proxied references still count once in the graph.
    assert retained_size([record,record._values,record._estimated_bytes])[0]==expected


def test_reference_weight_rejects_unfrozen_mutable_input():
    with pytest.raises(TypeError):readonly.frozen_reference_weight({'payload':'x'*8192})


def test_readonly_subclasses_are_captured_before_cached_weight_or_sharing():
    class Foreign(ReadonlyFields):
        __slots__=('mutable',)
        def __getitem__(self,key):return self.mutable[key]
    foreign=Foreign({'payload':'old'})
    object.__setattr__(foreign,'mutable',{'payload':'x'*8192})
    captured=ReadonlyFields({'nested':foreign})['nested'];copied=deepcopy(foreign)
    assert type(captured) is type(copied) is ReadonlyFields
    foreign.mutable['payload']='changed'
    assert captured['payload']==copied['payload']=='x'*8192
    assert captured.estimated_bytes>=retained_size([captured])[0]
