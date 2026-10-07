import pandas as pd
import csv

NOTE_COLUMNS = ["All Notes", "Note Author", "Note Created Date", "Note Date Modified", "Note Type"]
NOTE_DIVIDER = "\n---------------\n"


def load_column_filter(
    csv_path: str = "students.csv",
    available_columns: list = None,
    encoding: str = "cp1252",
) -> list:
    """Load column names from a CSV file (one column per line),
    resolving any quoting or whitespace differences against available_columns."""
    with open(csv_path, "r", encoding=encoding, errors="replace") as f:
        reader = csv.reader(f)
        raw_cols = [row[0].strip() for row in reader if row and row[0].strip()]

    if available_columns is None:
        return raw_cols

    resolved = []
    for col in raw_cols:
        if col in available_columns:
            resolved.append(col)
            continue
        norm_col = col.strip().strip('"').strip()
        match = None
        for ac in available_columns:
            if ac.strip().strip('"').strip() == norm_col:
                match = ac
                break
        if match is None:
            for ac in available_columns:
                if ac.strip().strip('"').strip().lower() == norm_col.lower():
                    match = ac
                    break
        if match is not None:
            resolved.append(match)
        else:
            print(f"Warning: column '{col}' from {csv_path} not found in input data.")
    return resolved


def write_output_csv(df: pd.DataFrame, output_path: str = "students_column_filter.csv") -> None:
    df.to_csv(output_path, index=False)
    print(f"Output written to {output_path}")


def write_duplicates_markdown(
    df: pd.DataFrame,
    id_column: str = "Unique ID",
    name_column: str = "First Name",
    ident_column: str = "ID",
    output_path: str = "notes_based_duplicate_removal.md",
    total_rows_before: int = None,
    total_rows_after: int = None,
) -> None:
    dup_mask = df[id_column].notna() & df[id_column].duplicated(keep=False)
    duplicates = df.loc[dup_mask, [id_column, name_column, ident_column]].sort_values(id_column)

    lines = ["# Notes-based Duplicate Removal", ""]
    if duplicates.empty:
        lines.append("No duplicate Unique IDs found.")
    else:
        num_ids = duplicates[id_column].nunique()
        num_dup_rows = len(duplicates)
        rows_removed = num_dup_rows - num_ids
        lines.append(
            f"Found **{num_ids}** Unique ID(s) with duplicate records "
            f"({num_dup_rows} rows total)."
        )
        lines.append(
            f"Merging collapsed those {num_dup_rows} rows down to {num_ids} "
            f"(one per Unique ID), removing **{rows_removed}** duplicate rows."
        )
        if total_rows_before is not None and total_rows_after is not None:
            lines.append(
                f"Overall: **{total_rows_before}** rows before merging &rarr; "
                f"**{total_rows_after}** rows after merging."
            )
        lines.append("")
        for unique_id, group in duplicates.groupby(id_column):
            lines.append(f"## Unique ID: {unique_id}")
            lines.append("")
            lines.append(f"| {name_column} | {ident_column} |")
            lines.append("|---|---|")
            for _, row in group.iterrows():
                lines.append(f"| {row[name_column]} | {row[ident_column]} |")
            lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Duplicate report written to {output_path}")


def merge_duplicate_notes(
    df: pd.DataFrame,
    id_column: str = "Unique ID",
    note_columns: list = None,
    divider: str = NOTE_DIVIDER,
) -> pd.DataFrame:
    """Collapse rows that share the same id_column into a single row.

    Ontraport exports one row per note, so a student with 4 notes shows up as
    4 duplicate rows differing only in the note_columns. This merges those
    rows into one, appending each row's note_columns values (separated by
    `divider`) so no note content is lost, and keeps the first non-null value
    for every other column.
    """
    if note_columns is None:
        note_columns = NOTE_COLUMNS

    def merge_group(group: pd.DataFrame) -> pd.Series:
        merged = {id_column: group.name}
        for col in group.columns:
            if col == id_column:
                continue
            if col in note_columns:
                values = [str(v).strip() for v in group[col] if pd.notna(v) and str(v).strip()]
                merged[col] = divider.join(values)
            else:
                non_null = group[col].dropna()
                merged[col] = non_null.iloc[0] if not non_null.empty else pd.NA
        return pd.Series(merged)

    has_id = df[id_column].notna()
    # pandas excludes the grouping column from `group` inside apply(), so
    # merge_group reads it via group.name instead of group[id_column].
    with_id = df[has_id].groupby(id_column, sort=False, group_keys=False).apply(
        merge_group, include_groups=False
    )
    without_id = df[~has_id]
    return pd.concat([with_id, without_id], ignore_index=True)[df.columns]


def write_duplicate_records_csv(
    df: pd.DataFrame,
    duplicate_ids,
    id_column: str = "Unique ID",
    output_path: str = "duplicate_records_merged.csv",
) -> None:
    """Write just the (already-merged) rows whose id_column was previously
    duplicated, so the merge result can be spot-checked without scrolling
    through the full output file."""
    subset = df[df[id_column].isin(duplicate_ids)]
    subset.to_csv(output_path, index=False)
    print(f"Duplicate records (merged) written to {output_path}")


def merge_duplicate_by_key(
    df: pd.DataFrame,
    key_columns: list,
    note_columns: list = None,
    divider: str = NOTE_DIVIDER,
) -> pd.DataFrame:
    """Same idea as merge_duplicate_notes, but groups rows by a composite key
    (e.g. First Name + Last Name + DOB) instead of a single id column, for
    cases where Ontraport assigned two different IDs to the same person.
    """
    if note_columns is None:
        note_columns = NOTE_COLUMNS

    def merge_group(group: pd.DataFrame) -> pd.Series:
        key_values = group.name if isinstance(group.name, tuple) else (group.name,)
        merged = dict(zip(key_columns, key_values))
        for col in group.columns:
            if col in key_columns:
                continue
            if col in note_columns:
                values = [str(v).strip() for v in group[col] if pd.notna(v) and str(v).strip()]
                merged[col] = divider.join(values)
            else:
                non_null = group[col].dropna()
                merged[col] = non_null.iloc[0] if not non_null.empty else pd.NA
        return pd.Series(merged)

    has_key = df[key_columns].notna().all(axis=1)
    with_key = df[has_key].groupby(key_columns, sort=False, group_keys=False).apply(
        merge_group, include_groups=False
    )
    without_key = df[~has_key]
    return pd.concat([with_key, without_key], ignore_index=True)[df.columns]


def write_key_duplicates_markdown(
    df: pd.DataFrame,
    key_columns: list,
    ident_column: str = "ID",
    output_path: str = "2Stage_First_LastName_DOB.md",
    total_rows_before: int = None,
    total_rows_after: int = None,
) -> None:
    dup_mask = df[key_columns].notna().all(axis=1) & df.duplicated(subset=key_columns, keep=False)
    duplicates = df.loc[dup_mask, key_columns + [ident_column]].sort_values(key_columns)

    lines = ["# Stage 2 Duplicate Removal (First Name + Last Name + DOB)", ""]
    if duplicates.empty:
        lines.append("No duplicate First Name + Last Name + DOB records found.")
    else:
        num_groups = len(duplicates.drop_duplicates(subset=key_columns))
        num_dup_rows = len(duplicates)
        rows_removed = num_dup_rows - num_groups
        lines.append(
            f"Found **{num_groups}** First Name + Last Name + DOB combination(s) with duplicate records "
            f"({num_dup_rows} rows total)."
        )
        lines.append(
            f"Merging collapsed those {num_dup_rows} rows down to {num_groups}, removing **{rows_removed}** duplicate rows."
        )
        if total_rows_before is not None and total_rows_after is not None:
            lines.append(
                f"Overall: **{total_rows_before}** rows before merging &rarr; "
                f"**{total_rows_after}** rows after merging."
            )
        lines.append("")
        header = " | ".join(key_columns + [ident_column])
        sep = "|".join(["---"] * (len(key_columns) + 1))
        for _, group in duplicates.groupby(key_columns):
            title = " / ".join(str(v) for v in group.iloc[0][key_columns].tolist())
            lines.append(f"## {title}")
            lines.append("")
            lines.append(f"| {header} |")
            lines.append(f"|{sep}|")
            for _, row in group.iterrows():
                cells = " | ".join(str(row[c]) for c in key_columns + [ident_column])
                lines.append(f"| {cells} |")
            lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Duplicate report written to {output_path}")

