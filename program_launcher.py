#!/usr/bin/python3
"""Isolated run/kill helper; never import application code from the cwd."""
import runpy
import sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
runpy.run_module('auralyn_terminal.program_cli', run_name='__main__')
