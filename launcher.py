#!/usr/bin/python3
"""Isolated launcher: does not import application modules from the working dir."""
import runpy
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
runpy.run_module("auralyn_terminal", run_name="__main__")
