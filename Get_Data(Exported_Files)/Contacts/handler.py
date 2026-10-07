import csv

import pandas as pd

NOTE_COLUMNS = ['All Notes', 'Note Author', 'Note Created Date', 'Note Date Modified', 'Note Type']
DIVIDER = '-' * 20

STAGE2_BLOCKS = [
    ('Filter: First Name + Last Name + First Name (2) + Last Name (2)',
     ['First Name', 'Last Name', 'First Name (2)', 'Last Name (2)']),
    ('Filter: Email + Email (2)', ['Email', 'Email (2)']),
    ('Filter: SMS Number + SMS Number (2)', ['SMS Number', 'SMS Number (2)']),
]


def load_data(xlsx_path='contacts.xlsx'):
    return pd.read_excel(xlsx_path, engine='openpyxl')


def load_filter_columns(csv_path='contacts.csv'):
    raw = pd.read_csv(csv_path, header=None)[0].dropna().tolist()
    return [c.strip() for c in raw]


def _normalize(name):
    return str(name).strip().strip('"').strip()


def find_duplicates(df, key_col='Unique ID'):
    dup_mask = df[key_col].duplicated(keep=False) & df[key_col].notna()
    dup_df = df[dup_mask].sort_values(key_col)

    print(f"Duplicate groups found on '{key_col}': {dup_df[key_col].nunique()}")
    print(f"Duplicate rows total: {len(dup_df)}")
    for uid, group in dup_df.groupby(key_col):
        for _, row in group.iterrows():
            cid = row['Contact ID']
            print(f"Unique ID {uid} | First Name: {row.get('First Name', '')} | "
                  f"Last Name: {row.get('Last Name', '')} | ID: {cid}")

    return dup_df


def merge_duplicate_notes(df, key_col='Unique ID', note_columns=NOTE_COLUMNS, divider=DIVIDER):
    df = df.reset_index(drop=True)
    seen = {}
    kept_rows = []

    for _, row in df.iterrows():
        key = row[key_col]
        if pd.isna(key):
            kept_rows.append(row)
            continue

        if key not in seen:
            base = row.copy()
            seen[key] = base
            kept_rows.append(base)
            continue

        base = seen[key]
        for col in note_columns:
            value = row[col]
            if pd.isna(value) or str(value).strip() == '':
                continue
            existing = base[col]
            if pd.isna(existing) or str(existing).strip() == '':
                base[col] = str(value)
            else:
                base[col] = f"{existing}\n{divider}\n{value}"

    merged_df = pd.DataFrame(kept_rows).reset_index(drop=True)
    print(f"Merged duplicate rows on '{key_col}': {len(df) - len(merged_df)} row(s) removed")
    return merged_df


def filter_columns(df, wanted_columns):
    normalized_lookup = {_normalize(c): c for c in df.columns}
    selected, missing = [], []
    for wanted in wanted_columns:
        actual = normalized_lookup.get(_normalize(wanted))
        if actual is not None:
            selected.append(actual)
        else:
            missing.append(wanted)

    if missing:
        print(f"Warning: {len(missing)} requested column(s) not found in source data:")
        for m in missing:
            print(f"  - {m}")

    return df[selected]


def export_csv(df, output_path):
    df.to_csv(output_path, index=False)
    print(f"Exported filtered data to: {output_path}")


def generate_markdown_report(df, dup_df, merged_df, filtered_df, key_col, output_md_path, output_csv_path):
    dup_groups = dup_df.groupby(key_col)

    lines = []
    lines.append("# Stage 1 Contact Filtering & Note-Merge Report")
    lines.append("")
    lines.append(f"- Source rows: **{len(df)}**")
    lines.append(f"- Source columns: **{df.shape[1]}**")
    lines.append(f"- Rows after merging duplicate notes: **{len(merged_df)}**")
    lines.append(f"- Rows removed by merge: **{len(df) - len(merged_df)}**")
    lines.append(f"- Filtered columns kept: **{filtered_df.shape[1]}**")
    lines.append(f"- Output file: `{output_csv_path}`")
    lines.append("")
    lines.append(f"## Merged groups (grouped by `{key_col}`)")
    lines.append("")
    lines.append(f"- Groups merged: **{dup_groups.ngroups}**")
    lines.append(f"- Rows merged into one: **{len(dup_df)}**")
    lines.append("")
    lines.append("| Contact ID | Unique ID | First Name | Last Name | Notes Merged |")
    lines.append("|---|---|---|---|---|")
    for uid, group in dup_groups:
        cid = group['Contact ID'].iloc[0]
        first = group['First Name'].iloc[0]
        last = group['Last Name'].iloc[0]
        lines.append(f"| {cid} | {uid} | {first} | {last} | {len(group)} |")

    with open(output_md_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

    print(f"Exported report to: {output_md_path}")


def load_csv(csv_path):
    return pd.read_csv(csv_path)


def _block_key(row, columns):
    values = []
    for col in columns:
        value = row[col]
        if pd.isna(value) or str(value).strip() == '':
            return None
        values.append(str(value).strip().lower())
    return tuple(values)


def find_block_duplicates(df, columns, claimed):
    candidates = df.loc[~df.index.isin(claimed)].copy()
    candidates['_key'] = candidates.apply(lambda r: _block_key(r, columns), axis=1)
    valid = candidates[candidates['_key'].notna()]
    dup_mask = valid['_key'].duplicated(keep=False)
    return valid[dup_mask].sort_values('_key')


def run_stage2_blocks(df, blocks=STAGE2_BLOCKS):
    claimed = set()
    results = []
    for title, columns in blocks:
        dup_df = find_block_duplicates(df, columns, claimed)
        claimed.update(dup_df.index)
        groups = dup_df['_key'].nunique()
        print(f"{title}: {groups} duplicate group(s), {len(dup_df)} row(s)")
        results.append((title, columns, dup_df))
    return results


def export_stage2_csv(results, output_path):
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        for title, columns, dup_df in results:
            writer.writerow([title])
            data = dup_df.drop(columns=['_key'])
            if not data.empty:
                writer.writerow(data.columns.tolist())
                for _, row in data.iterrows():
                    writer.writerow(row.tolist())
            else:
                writer.writerow(['No duplicates found'])
            writer.writerow([])
            writer.writerow([])

    print(f"Exported stage 2 duplicates to: {output_path}")


def generate_stage2_report(df, results, output_md_path, output_csv_path):
    lines = []
    lines.append("# Stage 2 Duplicate Detection Report")
    lines.append("")
    lines.append(f"- Seed rows: **{len(df)}**")
    lines.append(f"- Output file: `{output_csv_path}`")
    lines.append("")

    total_rows = 0
    for title, columns, dup_df in results:
        groups = dup_df['_key'].nunique() if not dup_df.empty else 0
        lines.append(f"## {title}")
        lines.append("")
        lines.append(f"- Duplicate groups: **{groups}**")
        lines.append(f"- Duplicate rows: **{len(dup_df)}**")
        lines.append("")

        if not dup_df.empty:
            lines.append("| Group | Contact ID | Unique ID | First Name | Last Name | Email | SMS Number |")
            lines.append("|---|---|---|---|---|---|---|")
            group_num = 0
            last_key = None
            for _, row in dup_df.iterrows():
                if row['_key'] != last_key:
                    group_num += 1
                    last_key = row['_key']
                lines.append(
                    f"| {group_num} | {row.get('Contact ID', '')} | {row.get('Unique ID', '')} | "
                    f"{row.get('First Name', '')} | {row.get('Last Name', '')} | "
                    f"{row.get('Email', '')} | {row.get('SMS Number', '')} |"
                )
            lines.append("")

        total_rows += len(dup_df)

    lines.append(f"**Total rows flagged across all blocks: {total_rows}**")

    with open(output_md_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

    print(f"Exported report to: {output_md_path}")
