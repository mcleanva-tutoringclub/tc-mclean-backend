import pandas as pd

from handler import (
    find_block_duplicates,
    print_block_duplicates,
    write_block_duplicate_report,
    write_block_duplicate_excel,
)

INPUT_CSV = "1stage_column_filter_with_notest.csv"
OUTPUT_CSV = "2stage_duplicate_filter.csv"
OUTPUT_MD = "2stage_duplicate_filter.md"
OUTPUT_XLSX = "2stage_duplicate_filter.xlsx"

df = pd.read_csv(INPUT_CSV)

results = find_block_duplicates(df)
print_block_duplicates(df, results)

write_block_duplicate_report(df, results, OUTPUT_CSV, OUTPUT_MD)
write_block_duplicate_excel(df, results, OUTPUT_XLSX)

print(f"\nWrote duplicate report ({len(df)} rows checked, none removed) to {OUTPUT_CSV}")
print(f"Wrote report to {OUTPUT_MD}")
print(f"Wrote color-coded workbook to {OUTPUT_XLSX}")
