import sys
from pathlib import Path

# Ensure repo root on path so `import lib...` and `apps.orchestrator...` work.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
