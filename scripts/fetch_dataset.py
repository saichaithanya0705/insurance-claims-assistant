"""Download a bounded educational sample, not the 100M-row dataset."""

import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

DATASET = "ziadatalabs/FreeInsuranceClaims100M"
ENDPOINT = "https://datasets-server.huggingface.co/rows"


def fetch_sample(output: Path, count: int = 3000, offset: int = 0) -> dict:
    if not 100 <= count <= 5000 or offset < 0:
        raise ValueError("Request 100–5000 rows and a nonnegative offset")
    rows = []
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for start in range(offset, offset + count, 100):
            for attempt in range(3):
                try:
                    response = client.get(
                        ENDPOINT,
                        params={
                            "dataset": DATASET,
                            "config": "default",
                            "split": "train",
                            "offset": start,
                            "length": min(100, offset + count - start),
                        },
                    )
                    response.raise_for_status()
                    page = response.json()
                    if any(item.get("truncated_cells") for item in page["rows"]):
                        raise ValueError("API returned truncated source cells")
                    rows.extend(item["row"] for item in page["rows"])
                    break
                except (httpx.HTTPError, KeyError, ValueError):
                    if attempt == 2:
                        raise
                    time.sleep(2**attempt)
    if len(rows) != count:
        raise ValueError(f"Requested {count} rows, received {len(rows)}")
    content = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    metadata = {
        "dataset": DATASET,
        "source_url": f"https://huggingface.co/datasets/{DATASET}",
        "api_endpoint": ENDPOINT,
        "config": "default",
        "split": "train",
        "offset": offset,
        "row_count": len(rows),
        "fetched_at": datetime.now(UTC).isoformat(),
        "rows_sha256": hashlib.sha256(content).hexdigest(),
        "license": "CC-BY-NC-4.0",
        "attribution": "ZiadataLabs — FreeInsuranceClaims100M",
        "synthetic": True,
        "sampling": "Contiguous bounded API slice; not a random or representative sample",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(".tmp")
    temp.write_text(json.dumps({"metadata": metadata, "rows": rows}, indent=2))
    temp.replace(output)
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=3000)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output", type=Path, default=Path("data/raw/claims_sample.json"))
    args = parser.parse_args()
    print(json.dumps(fetch_sample(args.output, args.count, args.offset), indent=2))
