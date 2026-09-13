"""Build the optional native row constructor with the executing CPython ABI."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).with_name("setup.py")), run_name="__main__")
