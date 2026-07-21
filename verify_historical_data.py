"""Cross-check the retained Mark Six JSON files against a public draw archive.

The raw yearly files are never changed.  Differences are written to a small,
auditable correction manifest consumed by ``historical_pattern_analysis.py``.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


ARCHIVE_URL = "https://lottery.hk/en/mark-six/results/{year}"


def load_local(data_dir: Path) -> dict[tuple[int, int], dict]:
    records: dict[tuple[int, int], dict] = {}
    for path in sorted(data_dir.glob("[0-9][0-9][0-9][0-9].json")):
        year = int(path.stem)
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("result", {}).get("data", {}).get("bodyList", [])
        for row in rows:
            issue = int(row["issue"])
            numbers = tuple(int(value) for value in row["preDrawCode"].split(","))
            records[(year, issue)] = {
                "year": year,
                "issue": issue,
                "date": row["preDrawDate"],
                "numbers": list(numbers),
            }
    return records


def fetch_year(year: int, timeout: int = 30) -> dict[tuple[int, int], dict]:
    url = ARCHIVE_URL.format(year=year)
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 historical-data-audit/1.0"},
        timeout=timeout,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    records: dict[tuple[int, int], dict] = {}
    for row in soup.select("tr"):
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        match = re.fullmatch(r"\d{2}/(\d{3})", cells[0].get_text(strip=True))
        if not match:
            continue
        issue = int(match.group(1))
        draw_date = datetime.strptime(cells[1].get_text(strip=True), "%d/%m/%Y").date()
        values = [
            int(item.get_text(strip=True))
            for item in row.select("li")
            if item.get_text(strip=True).isdigit()
        ]
        if len(values) != 7:
            values = [
                int(value)
                for value in re.findall(r"\b\d{1,2}\b", cells[2].get_text(" ", strip=True))
            ]
        if len(values) != 7:
            raise ValueError(f"cannot parse {year}/{issue:03d} from {url}")
        records[(year, issue)] = {
            "year": year,
            "issue": issue,
            "date": draw_date.isoformat(),
            "numbers": values,
            "source": url,
        }
    if not records:
        raise ValueError(f"no draw rows parsed from {url}")
    return records


def comparable(record: dict) -> tuple[str, tuple[int, ...], int]:
    numbers = tuple(record["numbers"])
    return record["date"], tuple(sorted(numbers[:6])), numbers[6]


def build_manifest(data_dir: Path) -> dict:
    local = load_local(data_dir)
    years = sorted({year for year, _ in local})
    remote: dict[tuple[int, int], dict] = {}
    for year in years:
        remote.update(fetch_year(year))

    local_only = sorted(set(local) - set(remote))
    remote_only = sorted(set(remote) - set(local))
    mismatches = [
        key
        for key in sorted(set(local) & set(remote))
        if comparable(local[key]) != comparable(remote[key])
    ]

    corrections = []
    for key in remote_only + mismatches:
        canonical = remote[key].copy()
        if key in remote_only:
            reason = ["missing_local_record"]
            local_record = None
        else:
            local_record = local[key]
            reason = []
            if local_record["date"] != canonical["date"]:
                reason.append("draw_date")
            if tuple(sorted(local_record["numbers"][:6])) != tuple(sorted(canonical["numbers"][:6])):
                reason.append("main_numbers")
            if local_record["numbers"][6] != canonical["numbers"][6]:
                reason.append("special_number")
        corrections.append(
            {
                **canonical,
                "reason": reason,
                "local": local_record,
            }
        )

    return {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_template": ARCHIVE_URL,
        "years": years,
        "counts": {
            "local": len(local),
            "archive": len(remote),
            "corrections": len(corrections),
            "missing_local": len(remote_only),
            "mismatched_local": len(mismatches),
            "local_not_in_archive": len(local_only),
        },
        "local_not_in_archive": [f"{year}-{issue:03d}" for year, issue in local_only],
        "corrections": corrections,
    }


def write_verified_dataset(data_dir: Path, output_dir: Path, manifest: dict) -> None:
    """Write corrected yearly JSON files without changing the raw source files."""
    corrections = {
        (int(item["year"]), int(item["issue"])): item
        for item in manifest.get("corrections", [])
    }
    output_dir.mkdir(parents=True, exist_ok=True)

    for source_path in sorted(data_dir.glob("[0-9][0-9][0-9][0-9].json")):
        year = int(source_path.stem)
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        verified_payload = copy.deepcopy(payload)
        body = verified_payload.setdefault("result", {}).setdefault("data", {}).setdefault(
            "bodyList", []
        )
        rows_by_issue = {int(row["issue"]): row for row in body}

        for (correction_year, issue), correction in corrections.items():
            if correction_year != year:
                continue
            row = rows_by_issue.get(issue)
            reasons = set(correction.get("reason", []))
            if row is None:
                row = {
                    "issue": issue,
                    "preDrawDate": correction["date"],
                    "preDrawCode": ",".join(str(value) for value in correction["numbers"]),
                }
                body.append(row)
                rows_by_issue[issue] = row
            else:
                if "draw_date" in reasons:
                    row["preDrawDate"] = correction["date"]
                if "main_numbers" in reasons or "special_number" in reasons:
                    row["preDrawCode"] = ",".join(
                        str(value) for value in correction["numbers"]
                    )

        body.sort(key=lambda row: int(row["issue"]), reverse=True)
        target_path = output_dir / source_path.name
        target_path.write_text(
            json.dumps(verified_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/verified_corrections_2010_2026.json"),
    )
    parser.add_argument(
        "--verified-dir", type=Path, default=Path("data_verified")
    )
    args = parser.parse_args()
    manifest = build_manifest(args.data_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_verified_dataset(args.data_dir, args.verified_dir, manifest)
    print(json.dumps(manifest["counts"], ensure_ascii=False))
    print(f"verified dataset: {args.verified_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
