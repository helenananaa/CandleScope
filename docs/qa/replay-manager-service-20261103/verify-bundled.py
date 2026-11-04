import pathlib,subprocess,os,json,hashlib,sys
root=pathlib.Path.cwd(); out=pathlib.Path(sys.argv[1]).resolve(); app=out/'Installed App/CandleScope.app'; res=app/'Contents/Resources'
files=[p for p in subprocess.check_output(['git','ls-files','-z','packages/candlescope-backtest-sdk/src','packages/candlescope-plugin-sdk/src']).decode().split('\0') if p]
assets=pathlib.Path('/Users/ryanliang/.codex/worktrees/history-study-navigation-links-20261102/CandleScope/output/history-study-navigation-main-current-plugins')
manifest={'sdk':{},'plugins':{},'mismatches':[]}
for rel in files:
 expected=hashlib.sha256((root/rel).read_bytes()).hexdigest(); actual=hashlib.sha256((res/rel).read_bytes()).hexdigest(); manifest['sdk'][rel]=expected
 if actual!=expected: manifest['mismatches'].append(rel)
for p in assets.rglob('*'):
 if p.is_file():
  rel=p.relative_to(assets); expected=hashlib.sha256(p.read_bytes()).hexdigest(); actual=hashlib.sha256((res/'python-runtime/plugins'/rel).read_bytes()).hexdigest(); manifest['plugins'][str(rel)]=expected
  if actual!=expected: manifest['mismatches'].append(str(rel))
(out/'sdk-plugin-source-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n'); print('SDK',len(files),'plugins',len(manifest['plugins']),'mismatches',manifest['mismatches']); assert not manifest['mismatches']
env=os.environ.copy(); env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=f'{res}/backend:{res}/python-runtime/site-packages',CANDLE_DATA_DIR=str(out/'test-state'))
program='''import pathlib,sys
res=pathlib.Path(sys.argv[1]).resolve()
import app.history_studies.repository as history,app.trading_accounts.journal as journal,app.backtest.strategy.python_runner as runner
import app.data_engine.data_manager.replay as replay_manager
for module in (history,journal,runner,replay_manager): assert pathlib.Path(module.__file__).resolve().is_relative_to(res/'backend'),module.__file__
assert pathlib.Path(runner.SDK_SRC).resolve().is_relative_to(res),runner.SDK_SRC
import pytest
raise SystemExit(pytest.main(['-q','-p','no:cacheprovider','backend/tests/test_history_studies.py','backend/tests/test_trading_accounts.py','backend/tests/test_python_strategy_runtime.py','backend/tests/test_replay_data_manager.py']))
'''
with (out/'backend-tests.log').open('w') as log: result=subprocess.run([str(res/'python-runtime/python/bin/python3'),'-B','-c',program,str(res)],env=env,stdout=log,stderr=subprocess.STDOUT)
print((out/'backend-tests.log').read_text()[-3000:]); assert result.returncode==0
signed=subprocess.run(['codesign','--verify','--deep','--strict',str(app)],text=True,capture_output=True); receipt={'exitCode':signed.returncode,'stdout':signed.stdout,'stderr':signed.stderr}; (out/'signature-before-native.json').write_text(json.dumps(receipt,indent=2)+'\n'); print(receipt); assert signed.returncode==0
