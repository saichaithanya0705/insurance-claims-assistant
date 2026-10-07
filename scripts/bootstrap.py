"""One-command setup and verification for a fresh clone.

    uv run python scripts/bootstrap.py check            # what is ready, what is missing
    uv run python scripts/bootstrap.py data             # download + verify the 100M-row Parquet (2.5 GB)
    uv run python scripts/bootstrap.py train            # train amount / resolution / fraud models
    uv run python scripts/bootstrap.py corpus           # build the Synapt claim-card corpus (local only)
    uv run python scripts/bootstrap.py ingest           # upload the corpus to Synapt (needs live .env)
    uv run python scripts/bootstrap.py all              # data + train + corpus (no external writes)
    uv run python scripts/bootstrap.py all --ingest     # ...and upload the corpus to Synapt

Every step is safe to re-run: existing downloads are verified and reused, models are retrained
only on request, and Synapt batches already uploaded are skipped (ledger).
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.dataset import COLUMNS, DATASET, FILENAME, ClaimsStore
from claims.settings import Settings

EXPECTED_ROWS = 100_000_000
CORPUS = ROOT / "artifacts" / "synapt" / "corpus-v3"


def say(mark: str, text: str):
    print(f"  [{mark}] {text}", flush=True)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def remote_sha256() -> str | None:
    """The hash Hugging Face publishes for the file (None if offline)."""
    try:
        from huggingface_hub import HfApi

        info = HfApi().get_paths_info(DATASET, [FILENAME], repo_type="dataset")
        return info[0].lfs.sha256 if info and info[0].lfs else None
    except Exception:  # noqa: BLE001 - offline or API change: fall back to the size check
        return None


def step_data(settings: Settings, args) -> bool:
    print("== Dataset (100M-row Parquet, 2.5 GB, CC BY-NC 4.0)")
    target = settings.claims_parquet_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file() or args.redownload:
        from huggingface_hub import hf_hub_download

        say("..", f"downloading {DATASET}/{FILENAME} (resumes if interrupted)")
        started = time.time()
        downloaded = Path(
            hf_hub_download(
                repo_id=DATASET, repo_type="dataset", filename=FILENAME, local_dir=str(target.parent)
            )
        )
        if downloaded.resolve() != target.resolve():
            downloaded.replace(target)
        say("ok", f"downloaded in {time.time() - started:.0f}s")
    else:
        say("ok", f"already present: {target}")
    say("..", "verifying SHA256 against the hash Hugging Face publishes")
    local, remote = sha256_of(target), remote_sha256()
    if remote is None:
        say("!!", f"could not reach Hugging Face to compare; local sha256 {local[:16]}...")
    elif local != remote:
        say("XX", "SHA256 differs from the published file; delete it and re-run `data`")
        return False
    else:
        say("ok", f"SHA256 matches the published file ({local[:16]}...)")
    store = ClaimsStore(target)
    try:
        rows = store.row_count()
        columns = [d[0] for d in store.connection.execute(f"SELECT * FROM {store.source} LIMIT 0").description]
        overview = store.overview()
    finally:
        store.close()
    if rows != EXPECTED_ROWS or columns != list(COLUMNS):
        say("XX", f"unexpected content: {rows:,} rows, columns {columns}")
        return False
    say("ok", f"{rows:,} rows; columns match the 13 key fields")
    say("ok", "status mix: " + ", ".join(f"{k} {v / rows:.1%}" for k, v in overview["by_status"].items()))
    return True


def step_train(settings: Settings, args) -> bool:
    print(f"== Models (sample of {settings.claims_train_rows:,} rows drawn from the Parquet file)")
    from claims.analytics import AnalyticsService

    if not settings.claims_parquet_path.is_file():
        say("XX", "dataset missing: run `bootstrap.py data` first")
        return False
    service = AnalyticsService(
        settings.claims_data_path,
        settings.claims_artifact_dir,
        settings.claims_parquet_path,
        settings.claims_train_rows,
        settings.claims_duckdb_memory,
    )
    status = service.status()
    if status.get("available") and not args.retrain:
        say("ok", f"already trained at {status.get('trained_at')} (use --retrain to rebuild)")
    else:
        started = time.time()
        status = service.train()
        say("ok" if status.get("available") else "XX", f"training finished in {time.time() - started:.0f}s")
    if not status.get("available"):
        say("XX", status.get("reason", "training failed"))
        return False
    metrics = status["metrics"]
    amount, resolution, fraud = metrics["amount"], metrics["resolution"], metrics["fraud"]
    say("ok", f"amount MAE ${amount['mae']:,.0f} vs baseline ${amount['baseline_mae']:,.0f}")
    say("ok", f"resolution MAE {resolution['mae']:.2f} d vs baseline {resolution['baseline_mae']:.2f} d")
    say("ok", f"fraud flag precision {fraud['precision']:.1%}, recall {fraud['recall']:.1%}, "
        f"PR-AUC {fraud['pr_auc_average_precision']:.3f} vs {fraud['baseline_pr_auc']:.3f} baseline")
    return True


def step_corpus(settings: Settings, args) -> bool:
    print(f"== Synapt corpus ({args.per_type * 5:,} claim cards; local files only)")
    from datetime import date

    from claims.corpus import build_corpus

    if not settings.claims_parquet_path.is_file():
        say("XX", "dataset missing: run `bootstrap.py data` first")
        return False
    store = ClaimsStore(settings.claims_parquet_path)
    try:
        manifest = build_corpus(store, CORPUS, per_type=args.per_type, cutoff=date(2026, 1, 1))
    finally:
        store.close()
    say("ok", f"{manifest['cards']:,} cards in {len(manifest['batches'])} batches -> {CORPUS}")
    return True


def step_ingest(settings: Settings, args) -> bool:
    print("== Upload corpus to Synapt")
    if settings.synapt_mode != "live":
        say("XX", "SYNAPT_MODE is not live. Fill the Synapt block of .env first (see docs/SETUP.md)")
        return False
    command = [sys.executable, str(ROOT / "scripts" / "synapt_ingest.py"), "ingest",
               "--corpus", str(CORPUS), "--chunk-size", "100"]
    if args.procedures:
        command.append("--procedures")
    return subprocess.run(command, cwd=ROOT, check=False).returncode == 0


def step_check(settings: Settings, args) -> bool:
    print("== Readiness check")
    ready = True
    say("ok", f"Python {sys.version.split()[0]} (uv enforces the supported range 3.11 to 3.13)")
    parquet = settings.claims_parquet_path
    if parquet.is_file():
        store = ClaimsStore(parquet)
        try:
            rows = store.row_count()
        finally:
            store.close()
        good = rows == EXPECTED_ROWS
        say("ok" if good else "XX", f"dataset {parquet.name}: {rows:,} rows")
        ready &= good
    else:
        say("XX", f"dataset missing at {parquet}  ->  bootstrap.py data")
        ready = False
    from claims.analytics import AnalyticsService

    models = AnalyticsService(settings.claims_data_path, settings.claims_artifact_dir).status()
    if models.get("available"):
        origin = models.get("origin", {})
        say("ok", f"models trained ({origin.get('sample_rows', '?')} rows sampled, {models['trained_at'][:10]})")
    else:
        say("XX", "models not trained  ->  bootstrap.py train")
        ready = False
    say("ok" if (CORPUS / "manifest.json").exists() else "..", f"corpus built: {(CORPUS / 'manifest.json').exists()}")
    say("ok" if settings.agent_mode == "live" else "..",
        f"agents: {settings.agent_mode} (key configured: {bool(settings.llm_api_key.get_secret_value())})")
    say("ok" if settings.judge_mode == "inline" else "..",
        f"independent judge: {settings.judge_mode} ({settings.judge_model or 'no JUDGE_MODEL set'})")
    if settings.synapt_mode == "live":
        import asyncio

        from claims.adapters import LiveSynaptAdapter

        async def probe():
            adapter = LiveSynaptAdapter(settings)
            stats = await adapter.call_read_tool("trident_get_stats", {"provider_id": settings.synapt_provider_id})
            return json.loads(stats["result"]) if isinstance(stats.get("result"), str) else stats

        try:
            stats = asyncio.run(probe())
            ledger = CORPUS / "ledger.jsonl"
            say("ok", f"Synapt provider {settings.synapt_provider_id}: {stats['doc_count']} documents, "
                f"{stats['chunks']} chunks; corpus batches uploaded: "
                f"{sum(1 for _ in ledger.open()) if ledger.exists() else 0}")
            for expansion in sorted((ROOT / "artifacts" / "synapt").glob("corpus-*/upload-ledger.jsonl")):
                manifest_path = expansion.parent / "manifest.json"
                if not manifest_path.exists():
                    continue
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                states = {}
                for line in expansion.read_text(encoding="utf-8").splitlines():
                    entry = json.loads(line)
                    if entry["provider"] != settings.synapt_provider_id:
                        raise ValueError("Expansion ledger belongs to a different provider")
                    states[entry["path"]] = entry["status"]
                verified = sum(b["cards"] for b in manifest["batches"]
                               if states.get(b["path"]) == "verified")
                pending = manifest["cards"] - verified
                say("ok" if not pending else "..",
                    f"{expansion.parent.name}: {verified:,}/{manifest['cards']:,} cards verified; "
                    f"{pending:,} pending verification (submitted does not mean searchable)")
                ready &= not pending
        except Exception as exc:  # noqa: BLE001 - any failure is a readiness problem to report
            say("XX", f"Synapt not reachable ({type(exc).__name__}); check .env credentials")
            ready = False
    else:
        say("..", "Synapt: fixture mode (no live retrieval). Set SYNAPT_MODE=live for the real integration")
    print("\nREADY" if ready else "\nNOT READY: resolve failures or unfinished verification above")
    return ready


STEPS = {"check": step_check, "data": step_data, "train": step_train, "corpus": step_corpus,
         "ingest": step_ingest}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("step", choices=[*STEPS, "all"])
    parser.add_argument("--redownload", action="store_true", help="download the Parquet again")
    parser.add_argument("--retrain", action="store_true", help="retrain even if models exist")
    parser.add_argument("--per-type", type=int, default=200, help="corpus cards per claim type")
    parser.add_argument("--ingest", action="store_true", help="with `all`: also upload to Synapt")
    parser.add_argument("--procedures", action="store_true", help="also upload the 5 procedures")
    args = parser.parse_args()
    settings = Settings()
    names = ["data", "train", "corpus"] + (["ingest"] if args.ingest else []) + ["check"] \
        if args.step == "all" else [args.step]
    for name in names:
        if not STEPS[name](settings, args):
            raise SystemExit(f"Step '{name}' did not complete.")
