"""Compatibility entry for existing desktop shortcuts."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).with_name('studio_launcher.pyw')), run_name='__main__')