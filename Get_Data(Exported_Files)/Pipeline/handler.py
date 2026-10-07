import csv

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill


def load_filter_columns(csv_path):
    """Read the keep-list of column names from pipelines.csv (one name per line)."""
    names = pd.read_csv(csv_path, header=None)[0].dropna().tolist()
    return [str(n).strip() for n in names]


def _normalize(name):
    """Strip whitespace and literal double-quote characters for lenient matching."""
    return name.strip().replace('"', "")


def filter_columns(df, columns):
    """Keep only the columns present in `columns`, in that order."""
    lookup = {_normalize(c): c for c in df.columns}
    existing = []
    missing = []
    for col in columns:
        actual = lookup.get(_normalize(col))
        if actual is not None:
            existing.append(actual)
        else:
            missing.append(col)
    if missing:
        print(f"Warning: {len(missing)} column(s) from pipelines.csv not found in data: {missing}")
    return df[existing]


def find_duplicates(df, subset=("ID", "Unique ID")):
    """Return rows sharing the same values across `subset` (duplicates on identity)."""
    subset = [c for c in subset if c in df.columns]
    return df[df.duplicated(subset=subset, keep=False)].sort_values(subset)


def print_duplicates(duplicates, unique_id_col="Unique ID", first_name_col="Primary Contact First Name", id_col="ID"):
    """Print each duplicate row as: Unique ID <uid> | First Name: <name> | ID: <id>"""
    if duplicates.empty:
        print("No duplicates found.")
        return
    print(f"Found {len(duplicates)} duplicate row(s) (by ID / Unique ID):")
    for _, row in duplicates.iterrows():
        uid = row.get(unique_id_col, "")
        first = row.get(first_name_col, "")
        rid = row.get(id_col, "")
        print(f"Unique ID {uid} | First Name: {first} | ID: {rid}")


NOTE_COLUMNS = ("All Notes", "Note Author", "Note Created Date", "Note Date Modified", "Note Type")
NOTE_DIVIDER = "-----------------------"


def merge_note_duplicates(df, id_cols=("ID", "Unique ID"), note_cols=NOTE_COLUMNS, divider=NOTE_DIVIDER):
    """Ontraport exports one row per note, duplicating every other column.
    Collapse rows sharing the same ID/Unique ID into a single row: non-note columns
    keep their first value, note columns are concatenated with `divider` between entries."""
    id_cols = [c for c in id_cols if c in df.columns]
    note_cols = [c for c in note_cols if c in df.columns]
    columns = list(df.columns)

    rows = []
    for name, group in df.groupby(id_cols, sort=False, dropna=False):
        key = name if isinstance(name, tuple) else (name,)
        merged = dict(zip(id_cols, key))
        first = group.iloc[0]
        for col in columns:
            if col in id_cols:
                continue
            if col in note_cols:
                values = [str(v).strip() for v in group[col] if pd.notna(v) and str(v).strip() != ""]
                merged[col] = f"\n{divider}\n".join(values)
            else:
                merged[col] = first[col]
        rows.append(merged)

    return pd.DataFrame(rows, columns=columns)


def write_report(rows_before_merge, merged_df, duplicates, csv_path, md_path,
                  id_col="Unique ID", first_name_col="Primary Contact First Name", secondary_id_col="ID"):
    """Write the final (filtered + note-merged) dataset to CSV, and a markdown report
    grouping the pre-merge duplicates by Unique ID with a First Name / ID sub-table each."""
    merged_df.to_csv(csv_path, index=False)

    rows_after_merge = len(merged_df)
    num_ids = duplicates[id_col].nunique() if not duplicates.empty else 0
    dup_rows = len(duplicates)
    removed = dup_rows - num_ids

    lines = [
        "# Notes-based Duplicate Removal",
        "",
        f"Found **{num_ids}** Unique ID(s) with duplicate records ({dup_rows} rows total).",
        f"Merging collapsed those {dup_rows} rows down to {num_ids} (one per Unique ID), "
        f"removing **{removed}** duplicate rows.",
        f"Overall: **{rows_before_merge}** rows before merging → **{rows_after_merge}** rows after merging.",
        "",
    ]

    if not duplicates.empty:
        for uid, group in duplicates.groupby(id_col, sort=True):
            lines.append(f"## Unique ID: {uid}")
            lines.append("")
            lines.append("| First Name | ID |")
            lines.append("|---|---|")
            for _, row in group.iterrows():
                first = row.get(first_name_col, "")
                rid = row.get(secondary_id_col, "")
                lines.append(f"| {first} | {rid} |")
            lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# --- Stage 2: cross-record duplicate detection (detect only, nothing removed) ---
# Each block below is run and reported INDEPENDENTLY (its own section) — a row can
# show up under more than one block; blocks are not merged into shared clusters.

BLOCKS = [
    {
        "name": "Block A: Primary Contact Email + Secondary Contact Email",
        "kind": "and",
        "fields": ["Primary Contact Email", "Secondary Contact Email"],
    },
    {
        "name": "Block B: Primary Contact First Name + Primary Contact Last Name + "
                "Secondary Contact First Name + Secondary Contact Last Name",
        "kind": "and",
        "fields": ["Primary Contact First Name", "Primary Contact Last Name",
                   "Secondary Contact First Name", "Secondary Contact Last Name"],
    },
    {
        "name": "Block C: (Primary Contact SMS Number or Primary Contact Home Phone or "
                "Primary Contact Address) + (Secondary Contact SMS Number or "
                "Secondary Contact Home Phone or Secondary Contact Address)",
        "kind": "or_and_or",
        "group_a": ["Primary Contact SMS Number", "Primary Contact Home Phone", "Primary Contact Address"],
        "group_b": ["Secondary Contact SMS Number", "Secondary Contact Home Phone", "Secondary Contact Address"],
    },
]


def _norm_value(value):
    """Normalize for comparison; blank/NaN values never count as a match."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().lower()
    return text or None


class _UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def _group_duplicates_by_key(df, fields):
    """Group row indices sharing the same non-blank value across every field in
    `fields` (an AND across all of them). Returns groups (row-index lists) with
    more than one member."""
    if any(c not in df.columns for c in fields):
        return []
    groups = {}
    for i in range(len(df)):
        key = tuple(_norm_value(df.at[i, c]) for c in fields)
        if any(v is None for v in key):
            continue
        groups.setdefault(key, []).append(i)
    return [sorted(idxs) for idxs in groups.values() if len(idxs) > 1]


def _group_duplicates_by_or_and_or(df, group_a_fields, group_b_fields):
    """Two rows are linked if they share a value on ANY field in group_a AND ANY
    field in group_b (the specific matching field may differ between the two
    groups). Returns connected-component groups (row-index lists) with more than
    one member."""
    n = len(df)
    group_a_fields = [c for c in group_a_fields if c in df.columns]
    group_b_fields = [c for c in group_b_fields if c in df.columns]
    if not group_a_fields or not group_b_fields:
        return []

    def build_index(cols):
        index = {}
        for col in cols:
            for i, v in enumerate(df[col]):
                key = _norm_value(v)
                if key is None:
                    continue
                index.setdefault((col, key), []).append(i)
        return index

    def matches_for(i, index, cols):
        matched = set()
        for col in cols:
            key = _norm_value(df.at[i, col])
            if key is None:
                continue
            for j in index.get((col, key), ()):
                if j != i:
                    matched.add(j)
        return matched

    index_a = build_index(group_a_fields)
    index_b = build_index(group_b_fields)

    uf = _UnionFind(n)
    for i in range(n):
        a_matches = matches_for(i, index_a, group_a_fields)
        if not a_matches:
            continue
        b_matches = matches_for(i, index_b, group_b_fields)
        for j in a_matches & b_matches:
            if j > i:
                uf.union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)
    return [sorted(idxs) for idxs in groups.values() if len(idxs) > 1]


def find_block_duplicates(df, blocks=BLOCKS):
    """Run each block as a duplicate check in priority order (A → B → C).
    Once a row is flagged as a duplicate in an earlier block it is excluded
    from all later blocks, so each record appears at most once."""
    df = df.reset_index(drop=True)
    seen = set()          # row indices already reported in a previous block
    results = []
    for block in blocks:
        if block["kind"] == "and":
            header_fields = block["fields"]
            groups = _group_duplicates_by_key(df, header_fields)
        else:
            header_fields = block["group_a"] + block["group_b"]
            groups = _group_duplicates_by_or_and_or(df, block["group_a"], block["group_b"])

        # Drop rows already claimed by an earlier block; keep groups with 2+ remaining rows
        filtered = []
        for idxs in groups:
            remaining = [i for i in idxs if i not in seen]
            if len(remaining) > 1:
                filtered.append(remaining)
        # Mark these rows as seen so later blocks skip them
        for idxs in filtered:
            seen.update(idxs)

        results.append((block["name"], header_fields, filtered))
    return results


EXTRA_CONTEXT_COLS = ("Web Inquiry - Student Name", "Date Added")


def _block_header(header_fields, id_col, uid_col, first_name_col, last_name_col):
    """Group, Unique ID, ID, First Name, Last Name, Web Inquiry - Student Name,
    Date Added, then the block's own fields (skipping First/Last Name if the
    block already includes them)."""
    base = ["Group", uid_col, id_col, first_name_col, last_name_col]
    context = [c for c in EXTRA_CONTEXT_COLS]
    extra = [f for f in header_fields if f not in (first_name_col, last_name_col)]
    return base + context + extra


def print_block_duplicates(df, results, id_col="ID", uid_col="Unique ID",
                            first_name_col="Primary Contact First Name",
                            last_name_col="Primary Contact Last Name"):
    """Print each block's duplicates as its own labeled section, with a Group
    number (same number = same duplicate group) plus First/Last Name for context."""
    df = df.reset_index(drop=True)
    for name, header_fields, groups in results:
        print(f"\nFilter: {name}")
        if not groups:
            print("  No duplicates found.")
            continue
        header = _block_header(header_fields, id_col, uid_col, first_name_col, last_name_col)
        print("  " + ", ".join(header))
        for group_num, idxs in enumerate(groups, start=1):
            for i in idxs:
                row = df.iloc[i]
                values = [group_num] + [row.get(c, "") for c in header[1:]]
                print("  " + ", ".join(str(v) for v in values))
            print()


def write_block_duplicate_report(df, results, csv_path, md_path, id_col="ID", uid_col="Unique ID",
                                  first_name_col="Primary Contact First Name",
                                  last_name_col="Primary Contact Last Name"):
    """Write a stacked-block report to CSV (Filter name row -> header row -> duplicate
    rows -> two blank rows -> next filter, matching the requested Excel-style layout),
    and the same report as markdown tables. Each duplicate row is tagged with a Group
    number (rows sharing a number are duplicates of each other) plus First/Last Name."""
    df = df.reset_index(drop=True)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for name, header_fields, groups in results:
            writer.writerow([f"Filter: {name}"])
            if not groups:
                writer.writerow(["No duplicates found."])
            else:
                header = _block_header(header_fields, id_col, uid_col, first_name_col, last_name_col)
                writer.writerow(header)
                for group_num, idxs in enumerate(groups, start=1):
                    for i in idxs:
                        row = df.iloc[i]
                        writer.writerow([group_num] + [row.get(c, "") for c in header[1:]])
                    writer.writerow([])
            writer.writerow([])
            writer.writerow([])

    lines = ["# Stage 2 Duplicate Detection Report (per block)", ""]
    for name, header_fields, groups in results:
        lines.append(f"## Filter: {name}")
        lines.append("")
        if not groups:
            lines.append("No duplicates found.")
            lines.append("")
            continue
        header = _block_header(header_fields, id_col, uid_col, first_name_col, last_name_col)
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "---|" * len(header))
        for group_num, idxs in enumerate(groups, start=1):
            for i in idxs:
                row = df.iloc[i]
                values = [group_num] + [row.get(c, "") for c in header[1:]]
                lines.append("| " + " | ".join(str(v) for v in values) + " |")
        lines.append("")

    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


RED_FILL_COLOR = "FFFFC7CE"  # odd-numbered groups get highlighted red; even groups stay plain
FILTER_FILL_COLOR = "FFD9D9D9"
HEADER_FILL_COLOR = "FFBFBFBF"


def write_block_duplicate_excel(df, results, xlsx_path, id_col="ID", uid_col="Unique ID",
                                 first_name_col="Primary Contact First Name",
                                 last_name_col="Primary Contact Last Name"):
    """Write the same stacked-block report to an .xlsx file. Every other duplicate
    group is filled red (1st, 3rd, 5th, ...) and the rest are left plain (2nd, 4th, ...),
    so consecutive groups are easy to tell apart at a glance."""
    df = df.reset_index(drop=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Stage 2 Duplicates"

    filter_fill = PatternFill(start_color=FILTER_FILL_COLOR, end_color=FILTER_FILL_COLOR, fill_type="solid")
    header_fill = PatternFill(start_color=HEADER_FILL_COLOR, end_color=HEADER_FILL_COLOR, fill_type="solid")
    red_fill = PatternFill(start_color=RED_FILL_COLOR, end_color=RED_FILL_COLOR, fill_type="solid")

    for name, header_fields, groups in results:
        ws.append([f"Filter: {name}"])
        for cell in ws[ws.max_row]:
            cell.fill = filter_fill
            cell.font = Font(bold=True)

        if not groups:
            ws.append(["No duplicates found."])
        else:
            header = _block_header(header_fields, id_col, uid_col, first_name_col, last_name_col)
            ws.append(header)
            for cell in ws[ws.max_row]:
                cell.fill = header_fill
                cell.font = Font(bold=True)

            for group_num, idxs in enumerate(groups, start=1):
                fill = red_fill if group_num % 2 == 1 else None
                for i in idxs:
                    data_row = df.iloc[i]
                    ws.append([group_num] + [data_row.get(c, "") for c in header[1:]])
                    if fill is None:
                        continue
                    for cell in ws[ws.max_row]:
                        cell.fill = fill

        ws.append([])
        ws.append([])

    for col_cells in ws.columns:
        length = max((len(str(c.value)) for c in col_cells if c.value is not None), default=10)
        ws.column_dimensions[col_cells[0].column_letter].width = min(max(length + 2, 10), 45)

    wb.save(xlsx_path)
