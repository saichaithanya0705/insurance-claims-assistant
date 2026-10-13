"""Write a claims-as-tickets workbook (.xlsx) for Synapt's Ticketing upload.

    python scripts/make_ticketing_sample.py --output artifacts/synapt/ticketing-sample
    python scripts/make_ticketing_sample.py --output artifacts/synapt/ticketing-2000 --per-type 400 --natural --name claims_tickets_2000

The console's Ticketing source takes only .xlsx. Column names must be plain identifiers (see COLUMNS): a first upload with
names such as "Claim Amount (USD)" was rejected by Synapt's Knowledge Service. The names follow a typical ticket export
(ticket_id, title, description, category, status, resolution, created, resolved) plus the claim fields. Rows are settled claims closed before the cutoff, drawn
deterministically per claim type. By default the synthetic fraud flag is over-sampled so a label has enough examples; with
``--natural`` rows are taken in hash order and the flag keeps the dataset's own rate. The policy ID
never appears and ticket IDs are the same lower-case aliases the cards use. The workbook is written with the standard
library only (zip and XML), so no spreadsheet package is needed. Nothing is uploaded.
"""

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from claims.core.settings import Settings
from claims.corpus.builder import CLAIM_TYPES
from claims.corpus.cards import claim_alias, claim_ticket
from claims.history.dataset import ClaimsStore

# Synapt turns a label field into a query parameter, a response key and a request field, so every column name must be a
# plain identifier (letters, digits and underscores, not starting with a digit). Spaces and brackets are rejected.
COLUMNS = (
    "ticket_id", "title", "description", "category", "region", "claim_amount_usd", "deductible_usd",
    "policyholder_tenure_years", "previous_claims", "days_from_incident_to_filing", "status", "resolution",
    "days_to_resolution", "fraud_flag", "created", "resolved",
)
CUTOFF = date(2026, 1, 1)


def sample_rows(store: ClaimsStore, per_type: int, flagged_per_type: int | None, seed: int) -> list[dict]:
    """Settled claims closed before the cutoff: per claim type, ``flagged_per_type`` flagged and the rest not, or, when
    ``flagged_per_type`` is None, the first ``per_type`` in hash order (the dataset's own fraud rate)."""
    sql = f"""
        SELECT * FROM {store.source}
        WHERE claim_status IN ('approved', 'denied')
          AND isfinite(days_to_resolution) AND days_to_resolution >= 0
          AND claim_filed_date + TRY_CAST(floor(days_to_resolution) AS INTEGER) < ?
          AND hash(claim_id, ?) % 2000 = 0
        ORDER BY hash(claim_id, ?)
    """
    pool = store.rows(sql, [CUTOFF, seed, seed + 1])
    chosen: list[dict] = []
    for kind in CLAIM_TYPES:
        of_kind = [r for r in pool if r["claim_type"] == kind]
        if flagged_per_type is None:
            if len(of_kind) < per_type:
                raise SystemExit(f"Not enough {kind} claims in the pool; raise the sampling rate")
            chosen += of_kind[:per_type]
            continue
        flagged = [r for r in of_kind if r["is_fraud_flagged_ground_truth"]][:flagged_per_type]
        plain = [r for r in of_kind if not r["is_fraud_flagged_ground_truth"]][: per_type - len(flagged)]
        if len(flagged) < flagged_per_type or len(plain) < per_type - flagged_per_type:
            raise SystemExit(f"Not enough {kind} claims in the pool; raise the sampling rate")
        chosen += flagged + plain
    return sorted(chosen, key=lambda r: r["claim_id"])


def ticket(row: dict) -> list:
    filed = date.fromisoformat(str(row["claim_filed_date"])[:10])
    incident = date.fromisoformat(str(row["incident_date"])[:10])
    delay = (filed - incident).days
    days = int(float(row["days_to_resolution"]))
    amount = float(row["claim_amount"])
    embedded = claim_ticket(row)
    return [
        claim_alias(row["claim_id"]),
        embedded["title"],
        embedded["description"],
        embedded["category"],
        embedded["region"],
        round(amount, 2),
        round(float(row["deductible"]), 2),
        round(float(row["policyholder_tenure_years"]), 1),
        int(row["previous_claims_count"]),
        delay,
        "closed",
        row["claim_status"],
        days,
        "flagged" if row["is_fraud_flagged_ground_truth"] else "not_flagged",
        filed.isoformat(),
        (filed + timedelta(days=days)).isoformat(),
    ]


def column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def write_xlsx(path: Path, header: tuple, rows: list[list], sheet: str = "Claims") -> None:
    """A minimal, standard workbook: one sheet, shared strings, a bold header row."""
    strings: dict[str, int] = {}

    def shared(text: str) -> int:
        return strings.setdefault(text, len(strings))

    def cell(ref: str, value, style: int = 0) -> str:
        if isinstance(value, bool) or not isinstance(value, int | float):
            return f'<c r="{ref}" t="s" s="{style}"><v>{shared(str(value))}</v></c>'
        return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'

    lines = ["<row r=\"1\">" + "".join(cell(f"{column_letter(i)}1", h, 1) for i, h in enumerate(header)) + "</row>"]
    for r, values in enumerate(rows, start=2):
        lines.append(f'<row r="{r}">' + "".join(cell(f"{column_letter(i)}{r}", v) for i, v in enumerate(values)) + "</row>")
    last = f"{column_letter(len(header) - 1)}{len(rows) + 1}"
    widths = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
        for i, w in enumerate([22, 48, 70, 12, 16, 14, 12, 14, 10, 12, 9, 11, 11, 14, 12, 12])
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{last}"/><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<cols>{widths}</cols><sheetData>{''.join(lines)}</sheetData></worksheet>"
    )
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(strings)}" '
        f'uniqueCount="{len(strings)}">'
        + "".join(f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s in strings)
        + "</sst>"
    )
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{escape(sheet)}" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
            "</Relationships>"
        ),
        "xl/styles.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
            "</styleSheet>"
        ),
        "xl/worksheets/sheet1.xml": sheet_xml,
        "xl/sharedStrings.xml": shared_xml,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--output", type=Path, default=Path("artifacts/synapt/ticketing-sample"))
    parser.add_argument("--per-type", type=int, default=60, help="tickets per claim type")
    parser.add_argument("--flagged-per-type", type=int, default=12, help="of which flagged (synthetic label)")
    parser.add_argument("--natural", action="store_true", help="do not over-sample the fraud flag (ignores --flagged-per-type)")
    parser.add_argument("--name", default="claims_tickets_sample", help="file name without the extension")
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    store = ClaimsStore(Settings().claims_parquet_path, memory_limit="3GB")
    try:
        rows = sample_rows(store, args.per_type, None if args.natural else args.flagged_per_type, args.seed)
    finally:
        store.close()
    table = [ticket(r) for r in rows]
    target = args.output / f"{args.name}.xlsx"
    write_xlsx(target, COLUMNS, table)
    summary = {
        "file": str(target), "tickets": len(table), "columns": list(COLUMNS),
        "per_type": {k: sum(r[3] == k for r in table) for k in CLAIM_TYPES},
        "flagged": sum(r[13] == "flagged" for r in table),
        "approved": sum(r[11] == "approved" for r in table),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "seed": args.seed,
        "flagged_per_type": None if args.natural else args.flagged_per_type,
        "note": (
            "fraud flag is not over-sampled: its rate is whatever the sampled settled claims carry" if args.natural
            else "fraud flag is over-sampled (not the dataset's 7.6% rate)"
        ) + "; policy IDs excluded; synthetic data, CC-BY-NC-4.0",
    }
    (args.output / f"{args.name}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
