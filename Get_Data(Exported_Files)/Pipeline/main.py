import pandas as pd

from handler import (
    load_filter_columns,
    filter_columns,
    find_duplicates,
    print_duplicates,
    merge_note_duplicates,
    write_report,
    find_block_duplicates,
    print_block_duplicates,
    write_block_duplicate_report,
)

# ── File paths ──────────────────────────────────────────────────────────────
DATA_FILE = "pipelines.xlsx"
FILTER_COLUMNS_FILE = "pipelines.csv"

STAGE1_CSV = "1stage_column_filter_with_notest.csv"
STAGE1_MD = "1stage_column_filter_with_notest.md"

STAGE2_CSV = "2stage_duplicate_filter.csv"
STAGE2_MD = "2stage_duplicate_filter.md"

# ── Stage 1: Column filter + note-based duplicate merge ─────────────────────
print("=" * 60)
print("STAGE 1: Column filter & note-based duplicate merge")
print("=" * 60)

df = pd.read_excel(DATA_FILE, engine="openpyxl")

columns_to_keep = load_filter_columns(FILTER_COLUMNS_FILE)
filtered_df = filter_columns(df, columns_to_keep)

duplicates = find_duplicates(filtered_df, subset=("ID", "Unique ID"))
print_duplicates(duplicates)

# Filter 1 ---------------------------------- merge Ontraport's one-row-per-note duplicates
merged_df = merge_note_duplicates(filtered_df)
# ------------------------------------------

write_report(len(filtered_df), merged_df, duplicates, STAGE1_CSV, STAGE1_MD)

print(f"\nWrote {len(merged_df)} rows x {len(merged_df.columns)} columns to {STAGE1_CSV}")
print(f"Wrote report to {STAGE1_MD}")

# ── Stage 2: Cross-record duplicate detection (detect only, nothing removed) ─
print()
print("=" * 60)
print("STAGE 2: Cross-record duplicate detection")
print("=" * 60)

stage2_df = pd.read_csv(STAGE1_CSV)

results = find_block_duplicates(stage2_df)
print_block_duplicates(stage2_df, results)

write_block_duplicate_report(stage2_df, results, STAGE2_CSV, STAGE2_MD)

print(f"\nWrote duplicate report ({len(stage2_df)} rows checked, none removed) to {STAGE2_CSV}")
print(f"Wrote report to {STAGE2_MD}")

