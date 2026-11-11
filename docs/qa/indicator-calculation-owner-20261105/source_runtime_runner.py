"""Source qualification runner; preserves the pinned core's venv launcher.

This is not an installed-package or Native acceptance launcher. It resolves
only current repository Pine/SDK modules, without mutating a retained runtime.
"""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[3]
args = sys.argv[1:]
while args and args[0] in ('-I','-B','-u'):
    args.pop(0)
if len(args) < 2 or args[0] != '-m' or not args[1].startswith('candlescope_plugin_pine_compat.'):
    raise SystemExit('Only repository Pine module qualification is supported')
sys.path[:0] = [str(ROOT/'packages'/name/'src') for name in (
    'candlescope-plugin-sdk','candlescope-plugin-pine-compat','candlescope-backtest-sdk')]
sys.argv = args[1:]
runpy.run_module(args[1],run_name='__main__')
