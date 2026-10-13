"""Write the additional handling procedures to a folder the uploader reads. Nothing is uploaded.

    python scripts/build_procedures.py --output artifacts/synapt/corpus-procedures-2026-10-12
    python scripts/synapt_ingest.py ingest --procedures-only --force --corpus artifacts/synapt/corpus-procedures-2026-10-12

`--force` is needed because the uploader refuses a provider that already holds claim cards; these are procedures, not cards.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from claims.corpus.procedures import build

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--output", type=Path, default=Path("artifacts/synapt/corpus-procedures-2026-10-12"))
    args = parser.parse_args()
    manifest = build(args.output)
    print(json.dumps({"output": str(args.output), "procedures": manifest["source_ids"]}, indent=2))
