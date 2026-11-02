from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from candlescope_plugin_python_indicator.author import (
    analyze, AuthorError, columns, parameters, output_columns,
)

FUNCTION = "def compute(bars, params):\n    return {'lines': {'main': bars['close']}}\n"


def test_static_analysis_does_not_execute_top_level_python(tmp_path):
    target = tmp_path/'must-not-exist'
    source = f"open({str(target)!r},'w').write('executed')\nraise RuntimeError()\n" + FUNCTION
    d = analyze(source)
    assert not target.exists()
    assert d.to_wire()['causality'] == 'unverified'
    assert d.to_wire()['recovery'] == 'reseed'
    assert d.window == 500


@pytest.mark.parametrize('source', [
    'async '+FUNCTION, FUNCTION.replace('compute(bars, params)', 'compute(x, y)'),
    '@decorator\n'+FUNCTION, FUNCTION*2, 'def compute(bars, params={}): pass',
    'INDICATOR = dict(window=3)\n'+FUNCTION,
    'INDICATOR = {}\nINDICATOR = {}\n'+FUNCTION,
    "INDICATOR = {'window': True}\n"+FUNCTION,
    "INDICATOR = {'unknown': 1}\n"+FUNCTION,
])
def test_invalid_author_contract_is_explicit(source):
    with pytest.raises(AuthorError):analyze(source)


def test_syntax_diagnostics_retain_source_position():
    with pytest.raises(AuthorError) as error:analyze('def compute(:\n')
    assert error.value.line == 1 and error.value.column


def declaration():
    return analyze("INDICATOR = {'parameters': [{'name': 'length', 'type': 'int', 'default': 3, 'min': 1, 'max': 10}]}\n"+FUNCTION)


def test_parameters_default_and_validation_share_declaration():
    d = declaration()
    assert dict(parameters(d, {})) == {'length': 3}
    assert parameters(d, {'length': 10})['length'] == 10
    with pytest.raises(TypeError):parameters(d, {})['length'] = 4


@pytest.mark.parametrize('value', [0, 11, True, 3.5, float('nan'), '3'])
def test_bad_parameters_cannot_be_silently_coerced(value):
    with pytest.raises(AuthorError):parameters(declaration(), {'length': value})


def test_unknown_parameters_rejected():
    with pytest.raises(AuthorError):parameters(declaration(), {'typo': 1})


def bar(t=1):
    return dict(time=t, open=1, high=2, low=1, close=2, volume=10, isClosed=True)


def test_columns_are_isolated_immutable_aligned_snapshot():
    rows = [bar(1),bar(2)];c=columns(rows);rows[0]['close']=999
    assert c['close'] == (2,2)
    assert c['time'] == (1,2)
    with pytest.raises(TypeError):c['close']=(999,)
    with pytest.raises(TypeError):c['close'][0]=999


@pytest.mark.parametrize('rows', [[bar(1),bar(1)], [bar(2),bar(1)],
                                  [{**bar(), 'volume': float('inf')}],
                                  [{**bar(), 'time': True}], [{**bar(), 'close': 10**1000}],
                                  [{**bar(), 'isClosed': 'true'}]])
def test_invalid_nonstandard_or_unordered_input_is_rejected(rows):
    with pytest.raises(AuthorError):columns(rows)


def test_warmup_is_none_and_not_fabricated_zero():
    assert output_columns(analyze(FUNCTION), {'lines': {'main': [None,2,3]}}, 3) == {'main':[None,2,3]}


@pytest.mark.parametrize('result', [
    {'lines':{'other':[1]}}, {'lines':{'main':[1,2]}}, {'lines':{'main':[float('nan')]}},
    {'lines':{'main':[True]}}, {'lines':{'main':[10**1000]}},
    {'lines':{'main':[(1,2)]}}, {'lines':{'main':[1]},'guessed_times':[1]},
])
def test_outputs_cannot_silently_misalign_or_leak_nonfinite_values(result):
    with pytest.raises(AuthorError):output_columns(analyze(FUNCTION),result,1)
