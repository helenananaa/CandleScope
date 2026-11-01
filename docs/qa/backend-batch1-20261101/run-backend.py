import json, os, subprocess, sys
from pathlib import Path
root=Path(__file__).resolve().parents[3]
files=json.loads((root/'docs/qa/r129-20261101/joint-files.json').read_text())
files+=['tests/test_bar_cache_protection.py','tests/test_trading_accounts.py','tests/test_account_product_integration.py','tests/test_plugin_live_accounts_v2.py','tests/test_manual_gap_audit.py']
files=sorted(set(files))
assert all((root/'backend'/f).exists() for f in files)
(root/'output/batch1-native-20261101/joint-files.json').write_text(json.dumps(files,indent=2)+'\n')
env=dict(os.environ,PYTHONPATH=str(root/'backend'),CANDLE_DATA_DIR='/tmp/candlescope-batch1-integration',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',CANDLESCOPE_REQUIRE_CCXT_FORK='1')
raise SystemExit(subprocess.call([sys.executable,'-m','pytest','-q','-p','pytest_asyncio.plugin','-p','anyio.pytest_plugin','-p','pytest_timeout','--timeout=90','--disable-warnings','--maxfail=3','--junitxml='+str(root/'output/batch1-native-20261101/backend-joint.xml'),*files],cwd=root/'backend',env=env))
