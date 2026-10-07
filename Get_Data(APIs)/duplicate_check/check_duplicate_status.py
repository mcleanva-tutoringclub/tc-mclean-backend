#!/usr/bin/env python3
"""
Stage 2 duplicate report (22 Sep 2026) -> which pipeline records still exist today?

STANDALONE and OFFLINE: no API calls, does not change any other file or the export flow.
It only READS:
    duplicate_check/stage2_duplicate_report.csv            (the 100 records / 47 groups from the report)
    export_data/pipelines/pipelines_readable.csv            (your latest pipelines download)
and WRITES one new file, in this same duplicate_check folder:
    duplicate_check/stage2_duplicate_status.csv

Status per record:
    Available  - the pipeline (same ID) is still in Ontraport
    Removed    - the pipeline is no longer in Ontraport (merged / deleted by the client)

Group Status (per duplicate group):
    Resolved - 1 record kept        the client merged the group
    Still duplicated - N left       more than one record of the group still exists
    All removed - check             no record of the group is left (verify nothing was lost)

Run (from the Get_Data(APIs) folder):
    python duplicate_check\\check_duplicate_status.py
    python duplicate_check\\check_duplicate_status.py --pipelines path\\to\\pipelines_readable.csv
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_REPORT = os.path.join(HERE, "stage2_duplicate_report.csv")
DEFAULT_PIPELINES = os.path.join(ROOT, "export_data", "pipelines", "pipelines_readable.csv")
DEFAULT_OUT = os.path.join(HERE, "stage2_duplicate_status.csv")   # saved next to this script

# Current values copied from the pipelines file for records that still exist (if those columns exist)
CURRENT_COLUMNS = ["Primary Contact", "Pipeline Stage", "Pipeline Status", "Date Modified", "Owner"]


def read_csv(path):
    csv.field_size_limit(2 ** 31 - 1)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return reader.fieldnames or [], list(reader)


def main():
    ap = argparse.ArgumentParser(description="Check which Stage 2 duplicate records still exist.")
    ap.add_argument("--report", default=DEFAULT_REPORT)
    ap.add_argument("--pipelines", default=DEFAULT_PIPELINES)
    ap.add_argument("--out", default=DEFAULT_OUT)
    a = ap.parse_args()

    for p in (a.report, a.pipelines):
        if not os.path.exists(p):
            sys.exit(f"Not found: {p}\nRun get_pipelines.py first, or pass --pipelines <file>.")

    report_cols, report = read_csv(a.report)
    pipe_cols, pipelines = read_csv(a.pipelines)
    id_col = "ID" if "ID" in pipe_cols else next((c for c in pipe_cols if c.lower() == "id"), None)
    uid_col = "Unique ID" if "Unique ID" in pipe_cols else None
    if not id_col:
        sys.exit(f"No 'ID' column in {a.pipelines}")

    by_id = {str(r[id_col]).strip(): r for r in pipelines}
    by_uid = {str(r[uid_col]).strip(): r for r in pipelines} if uid_col else {}
    current_cols = [c for c in CURRENT_COLUMNS if c in pipe_cols]

    # 1. status per record
    rows = []
    for r in report:
        rid, uid = r["ID"].strip(), r["Unique ID"].strip()
        cur = by_id.get(rid)
        note = ""
        if cur is None and uid in by_uid:  # same record, ID changed (unexpected, but don't call it removed)
            cur = by_uid[uid]
            note = f"found by Unique ID under ID {cur[id_col]}"
        elif cur is not None and uid_col and str(cur.get(uid_col, "")).strip() not in ("", uid):
            note = f"ID exists but Unique ID is now {cur.get(uid_col)} (report: {uid}) - check"
        out = dict(r)
        out["Status"] = "Available" if cur is not None else "Removed"
        out["Note"] = note
        for c in current_cols:
            out[f"Current {c}"] = cur.get(c, "") if cur is not None else ""
        rows.append(out)

    # 2. status per group
    groups = defaultdict(list)
    for o in rows:
        groups[(o["Block"], o["Group"])].append(o)
    summary = defaultdict(int)
    for key, members in groups.items():
        left = [m for m in members if m["Status"] == "Available"]
        if len(left) == 1:
            gs = "Resolved - 1 record kept"
        elif len(left) > 1:
            gs = f"Still duplicated - {len(left)} left"
        else:
            gs = "All removed - check"
        summary[gs.split(" - ")[0]] += 1
        kept = ", ".join(m["ID"] for m in left)
        for m in members:
            m["Records Left In Group"] = len(left)
            m["Group Status"] = gs
            m["Kept ID(s)"] = kept

    cols = report_cols + ["Status", "Group Status", "Records Left In Group", "Kept ID(s)"] + \
        [f"Current {c}" for c in current_cols] + ["Note"]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    avail = sum(1 for o in rows if o["Status"] == "Available")
    print(f"Pipelines file : {a.pipelines}  ({len(pipelines)} records)")
    print(f"Report records : {len(rows)} in {len(groups)} groups")
    print(f"  Available    : {avail}")
    print(f"  Removed      : {len(rows) - avail}")
    print("Groups:")
    for k in ("Resolved", "Still duplicated", "All removed"):
        print(f"  {k:<16}: {summary.get(k, 0)}")
    still = sorted({(o['Block'], int(o['Group'])) for o in rows if o['Group Status'].startswith('Still')})
    if still:
        print("  still duplicated: " + ", ".join(f"Block {b} group {g}" for b, g in still))
    notes = [o for o in rows if o["Note"]]
    if notes:
        print(f"  {len(notes)} record(s) need a look - see the Note column")
    print(f"Written: {a.out}")


if __name__ == "__main__":
    main()
