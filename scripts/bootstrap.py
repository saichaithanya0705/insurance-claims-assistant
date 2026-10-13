"""One-command setup and verification for a fresh clone.

    uv run python scripts/bootstrap.py check            # what is ready, what is missing
    uv run python scripts/bootstrap.py data             # download + verify the 100M-row Parquet (2.5 GB)
    uv run python scripts/bootstrap.py train            # train amount / resolution / fraud models
    uv run python scripts/bootstrap.py corpus           # build the Synapt profile-card corpus (local only)
    uv run python scripts/bootstrap.py ingest           # upload the procedures to an EMPTY Synapt provider (claims: console Ticketing)
    uv run python scripts/bootstrap.py all              # data + train + corpus (no external writes)
    uv run python scripts/bootstrap.py all --ingest     # ...and upload the procedures to Synapt

Every step is safe to re-run: existing downloads are verified and reused, models are retrained
only on request, and Synapt batches already uploaded are skipped (ledger).
"""

import argparse
import hashlib
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.core.settings import Settings
from claims.history.dataset import COLUMNS, DATASET, FILENAME, ClaimsStore

EXPECTED_ROWS = 100_000_000
CORPUS = ROOT / "artifacts" / "synapt" / "corpus-profile-balanced-2026-10-09"


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
    from claims.ml.analytics import AnalyticsService

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
    print(f"== Synapt profile corpus ({args.per_type * 5:,} claim cards; local files only)")
    from datetime import date

    from claims.corpus.profile_cards import build_profile_corpus

    if (CORPUS / "manifest.json").exists():
        say("ok", f"already built at {CORPUS}")
        return True
    if not settings.claims_parquet_path.is_file():
        say("XX", "dataset missing: run `bootstrap.py data` first")
        return False
    store = ClaimsStore(settings.claims_parquet_path)
    try:
        manifest = build_profile_corpus(store, CORPUS, per_type=args.per_type, cutoff=date(2026, 1, 1))
    finally:
        store.close()
    say("ok", f"{manifest['cards']:,} cards in {len(manifest['batches'])} batches -> {CORPUS}")
    return True


def step_ingest(settings: Settings, args) -> bool:
    """Procedures only. Past claims belong in the provider's ticket store, not its documents (claim cards uploaded as
    documents added almost nothing to the graph and were removed on 13 October 2026; docs/SYNAPT_INTEGRATION.md)."""
    print("== Upload procedures to Synapt (the provider in .env must be new and empty)")
    procedures = [sys.executable, str(ROOT / "scripts" / "synapt_ingest.py"), "ingest",
                  "--corpus", str(CORPUS), "--procedures-only", "--chunk-size", "100"]
    # Submission is asynchronous: confirm afterwards with scripts/verify_synapt_store.py.
    ok = subprocess.run(procedures, cwd=ROOT, check=False).returncode == 0
    print("   Past claims go in through the Synapt console (Data Ingestion, Ticketing), which has no MCP route:")
    print("   build the workbook with scripts/make_ticketing_sample.py (see data/synapt/README.md) and upload it there.")
    return ok


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
    from claims.ml.analytics import AnalyticsService

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
    import asyncio

    from claims.synapt.adapter import LiveSynaptAdapter
    from claims.synapt.inventory import (
        INVENTORY_PATH,
        load_expected,
        summary_lines,
        verify_store,
    )

    async def probe():
        # Compares the live provider with the committed inventory, so every machine gets the same
        # answer without a local upload ledger (artifacts/ is not in Git).
        adapter = LiveSynaptAdapter(settings)
        return await verify_store(adapter, settings.synapt_provider_id, load_expected(ROOT / INVENTORY_PATH))

    try:
        report = asyncio.run(probe())
        say("ok", f"Synapt provider {settings.synapt_provider_id} reachable; verified against "
            f"data/synapt/expected_inventory.json")
        for mark, text in summary_lines(report):
            say(mark, text)
        ready &= report["ok"]
    except Exception as exc:  # noqa: BLE001 - any failure is a readiness problem to report
        say("XX", f"Synapt not reachable ({type(exc).__name__}); check .env credentials")
        ready = False
    print("\nREADY" if ready else "\nNOT READY: resolve failures or unfinished verification above")
    return ready


STEPS = {"check": step_check, "data": step_data, "train": step_train, "corpus": step_corpus,
         "ingest": step_ingest}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("step", choices=[*STEPS, "all"])
    parser.add_argument("--redownload", action="store_true", help="download the Parquet again")
    parser.add_argument("--retrain", action="store_true", help="retrain even if models exist")
    parser.add_argument("--per-type", type=int, default=2000, help="corpus cards per claim type")
    parser.add_argument("--ingest", action="store_true", help="with `all`: also upload the procedures to Synapt")
    parser.add_argument("--procedures", action="store_true", help="also upload the 5 procedures")
    args = parser.parse_args()
    settings = Settings()
    names = ["data", "train", "corpus"] + (["ingest"] if args.ingest else []) + ["check"] \
        if args.step == "all" else [args.step]
    for name in names:
        if not STEPS[name](settings, args):
            raise SystemExit(f"Step '{name}' did not complete.")
