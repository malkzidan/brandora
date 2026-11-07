import os
import sys
from pathlib import Path

# the module-level `app` in main.py is created on import; tests run on the deterministic provider (no key, no network)
os.environ["AI_PROVIDER"] = "rules"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
