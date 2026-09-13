from pathlib import Path
import os
from setuptools import Extension, setup

root = Path(__file__).resolve().parent
setup(
    name="candlescope-backtest-native",
    version="0.1.0",
    packages=[],
    ext_modules=[Extension("app.backtest.strategy._native_rows", [str(root / "rows.c")], depends=[str(root / "executor.c")],
                           extra_compile_args=["/O2"] if os.name == "nt" else ["-O3"])],
)
