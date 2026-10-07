"""Keep Currency Wars runtime data inside this SRC checkout."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / 'state' / 'currency_wars'
EVIDENCE_DIR = ROOT / 'log' / 'currency_wars'
