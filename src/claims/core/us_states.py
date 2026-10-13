"""State code to state name, loaded once for the claim cards, the intake reader and the saved-case search."""

import json
from pathlib import Path

STATE_NAMES = json.loads(Path(__file__).with_name("us_states.json").read_text(encoding="utf-8"))
