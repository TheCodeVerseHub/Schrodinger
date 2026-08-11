"""Pytest configuration for the CodeVerse bot.

The bot adds its ``src/`` directory to ``sys.path`` at runtime (see
``main.py``), so modules are imported as ``events.message_handler``,
``commands.appeals``, etc. Mirror that here so tests exercise the same
imports the running bot uses.
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")

for path in (PROJECT_ROOT, SRC_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)
