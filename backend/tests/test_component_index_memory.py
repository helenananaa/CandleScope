"""Counted component indexes preserve dictionary/snapshot mutation contracts."""
from copy import copy,deepcopy
import pickle

import pytest

from app.data_engine.bar_aggregator.component_memory import ComponentSnapshots
from app.data_engine.memory_budget import retained_size
from app.data_engine.readonly import ReadonlyFields


def record(size):
    return ReadonlyFields({'value':'x'*size,'source_ref':{'series':'source','proof':'y'*size}})


def covered(index):
    assert index.estimated_bytes>=retained_size([index])[0]


def test_normal_mutations_change_payload_weights_and_release_metadata():
    index=ComponentSnapshots();empty=index.estimated_bytes
    small,large=record(10),record(8192)
    index['first']=small;covered(index);before=index.estimated_bytes
    index['first']=large;covered(index);assert index.estimated_bytes>before+8000
    proof=index.source_proof_bytes;assert proof>8192
    index.update({'second':small},third=large);covered(index)
    assert index.setdefault('third',small) is large
    assert index.setdefault('fourth',small) is small
    index |= {'fifth':large};covered(index)
    assert index.pop('missing',None) is None
    with pytest.raises(KeyError):index.pop('missing')
    with pytest.raises(TypeError):index.pop('missing',1,2)
    assert index.popitem()==('fifth',large)
    del index['third'];covered(index)
    index['first']=small;covered(index);assert index.source_proof_bytes<proof
    index.clear();assert not index and index.estimated_bytes==empty
    assert index.source_proof_bytes==index.foreign_entries==0


@pytest.mark.parametrize('copier',[copy,deepcopy,lambda value:value.copy(),lambda value:ComponentSnapshots(value)])
def test_copies_keep_immutable_values_and_independent_mutable_index(copier):
    value=record(8192);index=ComponentSnapshots(first=value)
    cloned=copier(index);covered(cloned)
    assert cloned is not index and cloned['first'] is value
    cloned['first']=record(1)
    assert index['first'] is value
    assert cloned.estimated_bytes<index.estimated_bytes
    del index['first'];assert cloned


def test_foreign_nested_mutation_is_measured_without_changing_aliasing():
    foreign={'proof':{'text':'small'}}
    index=ComponentSnapshots(foreign=foreign,known=record(100))
    assert index['foreign'] is foreign and index.foreign_entries==1
    before=index.estimated_bytes;foreign['proof']['text']='z'*8192
    covered(index);assert index.estimated_bytes>before+8000
    shallow=index.copy();assert shallow['foreign'] is foreign
    detached=index.publication_copy({});assert detached['foreign'] is not foreign
    foreign['proof']['text']='again'
    assert detached['foreign']['proof']['text']=='z'*8192
    del index['foreign'];assert index.foreign_entries==0
    covered(index)


def test_pure_immutable_usage_reads_cached_weights_without_iterating_values(monkeypatch):
    index=ComponentSnapshots((str(i),record(256)) for i in range(97))
    before=index.estimated_bytes
    def forbidden(*args):raise AssertionError('unexpected immutable record scan')
    monkeypatch.setattr(ReadonlyFields,'__iter__',forbidden)
    assert index.estimated_bytes==before and index.source_proof_bytes>0


def test_foreign_dictionary_pickle_and_fromkeys_preserve_mutation_accounting():
    index=ComponentSnapshots.fromkeys(['one','two'],{'value':'x'*8192})
    assert index['one'] is index['two']
    restored=pickle.loads(pickle.dumps(index))
    assert restored==index and restored['one'] is restored['two']
    restored['one']['value']='y'*16384;covered(restored)
    assert restored.estimated_bytes>index.estimated_bytes
    restored.clear();assert restored.foreign_entries==0


def test_update_error_keeps_prior_valid_changes_and_weights():
    index=ComponentSnapshots()
    with pytest.raises(ValueError):index.update([('valid',record(8192)),('bad',)])
    assert list(index)==['valid'];covered(index)
