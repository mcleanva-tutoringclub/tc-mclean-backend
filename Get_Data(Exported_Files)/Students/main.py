import pandas as pd
import csv
from handler import (
    load_column_filter,
    merge_duplicate_notes,
    write_duplicates_markdown,
    write_output_csv,
    merge_duplicate_by_key,
)

def main():
    print("=== Loading input data ===")
    input_path = "students.xlsx"
    df = pd.read_excel(input_path, engine="openpyxl")
    
    total_rows_before = len(df)
    total_cols_before = len(df.columns)
    
    # Filter columns to only those specified in students.csv
    filter_columns = load_column_filter("students.csv", available_columns=list(df.columns))
    df = df[filter_columns]
    print(f"Loaded {total_rows_before} rows. Column filter applied: {total_cols_before} -> {len(df.columns)} columns.")

    print("\n=== Stage 1: Note deduplication by Unique ID ===")
    
    # Write stage 1 markdown report
    write_duplicates_markdown(
        df,
        id_column="Unique ID",
        name_column="First Name",
        ident_column="ID",
        output_path="1Stage_Notes_Duplicate_Removal.md",
        total_rows_before=total_rows_before,
    )

    df_stage1 = merge_duplicate_notes(df, id_column="Unique ID")
    total_rows_after_stage1 = len(df_stage1)
    
    write_output_csv(df_stage1, output_path="1Stage_Output.csv")
    print(f"Stage 1 completed: {total_rows_before} -> {total_rows_after_stage1} rows ({len(df_stage1.columns)} columns).")

    print("\n=== Stage 2: First Name + Last Name + DOB / Email / SMS Number dedup ===")
    
    PASSES = [
        ("First Name + Last Name + DOB", ["First Name", "Last Name", "DOB"]),
        ("Email + First Name", ["Email", "First Name"]),
        ("SMS Number + First Name", ["SMS Number", "First Name"]),
    ]
    IDENT_COLUMN = "ID"
    
    df_stage2 = df_stage1.copy()
    report_sections = []
    
    duplicates_csv_path = "2Stage_Duplicates_Found.csv"
    with open(duplicates_csv_path, "w", newline="", encoding="utf-8") as dup_file:
        writer = csv.writer(dup_file)
        
        for label, key_columns in PASSES:
            dup_mask = df_stage2[key_columns].notna().all(axis=1) & df_stage2.duplicated(subset=key_columns, keep=False)
            duplicates = df_stage2.loc[dup_mask, key_columns + [IDENT_COLUMN]].sort_values(key_columns)
            
            print(f"--- {label} ---")
            writer.writerow([f"Filter: {label}"])
            if duplicates.empty:
                print("No duplicates found.")
                writer.writerow(["No duplicates found."])
            else:
                num_groups = len(duplicates.drop_duplicates(subset=key_columns))
                print(f"Found {num_groups} combination(s) with duplicate records ({len(duplicates)} rows total).")
                writer.writerow(key_columns + [IDENT_COLUMN])
                for _, group in duplicates.groupby(key_columns):
                    for _, row in group.iterrows():
                        writer.writerow([row[c] for c in key_columns] + [row[IDENT_COLUMN]])
            writer.writerow([])
            writer.writerow([])
            
            rows_before_pass = len(df_stage2)
            df_stage2 = merge_duplicate_by_key(df_stage2, key_columns)
            rows_after_pass = len(df_stage2)
            
            report_sections.append((label, key_columns, duplicates, rows_before_pass, rows_after_pass))
            
    total_rows_after_stage2 = len(df_stage2)
    print(f"Stage 2 duplicates written to {duplicates_csv_path}")
    
    write_output_csv(df_stage2, output_path="2Stage_Final_Output.csv")
    
    # Write combined markdown for stage 2
    lines = [
        "# Stage 2 Duplicate Removal (First+Last+DOB, then Email+First Name, then SMS+First Name)",
        "",
        f"Overall: **{total_rows_after_stage1}** rows before -> **{total_rows_after_stage2}** rows after (3 passes, applied in sequence).",
        "",
    ]
    for label, key_columns, duplicates, before, after in report_sections:
        lines.append(f"## Pass: {label}")
        lines.append("")
        if duplicates.empty:
            lines.append("No duplicates found.")
            lines.append("")
            continue
            
        num_groups = len(duplicates.drop_duplicates(subset=key_columns))
        num_dup_rows = len(duplicates)
        rows_removed = before - after
        lines.append(
            f"Found **{num_groups}** combination(s) with duplicate records ({num_dup_rows} rows total). "
            f"Removed **{rows_removed}** duplicate rows ({before} -> {after})."
        )
        lines.append("")
        header = " | ".join(key_columns + [IDENT_COLUMN])
        sep = "|".join(["---"] * (len(key_columns) + 1))
        for _, group in duplicates.groupby(key_columns):
            title = " / ".join(str(v) for v in group.iloc[0][key_columns].tolist())
            lines.append(f"### {title}")
            lines.append("")
            lines.append(f"| {header} |")
            lines.append(f"|{sep}|")
            for _, row in group.iterrows():
                cells = " | ".join(str(row[c]) for c in key_columns + [IDENT_COLUMN])
                lines.append(f"| {cells} |")
            lines.append("")
            
    with open("2Stage_Report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("Stage 2 report written to 2Stage_Report.md")
    
if __name__ == "__main__":
    main()
