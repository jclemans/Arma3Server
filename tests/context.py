"""Make the project modules importable from the repo root or container root."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# In the image the modules live at /, not in a project directory.
if "/" not in sys.path:
    sys.path.insert(0, "/")
