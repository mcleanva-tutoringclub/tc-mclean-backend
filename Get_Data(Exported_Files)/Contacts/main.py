import handler

KEY_COL = 'Unique ID'
STAGE1_CSV = '1stage_Filtered_Column_with_note.csv'
STAGE1_MD = '1stage_Filtered_Column_with_note.md'
STAGE2_CSV = '2stage_Duplicates_by_Block.csv'
STAGE2_MD = '2stage_Duplicates_by_Block.md'

# Stage 1: filter columns + merge duplicate Ontraport note-export rows
df = handler.load_data('contacts.xlsx')
wanted_columns = handler.load_filter_columns('contacts.csv')

dup_df = handler.find_duplicates(df, key_col=KEY_COL)
merged_df = handler.merge_duplicate_notes(df, key_col=KEY_COL)
filtered_df = handler.filter_columns(merged_df, wanted_columns)

handler.export_csv(filtered_df, STAGE1_CSV)
handler.generate_markdown_report(df, dup_df, merged_df, filtered_df, KEY_COL, STAGE1_MD, STAGE1_CSV)

# Stage 2: fuzzy duplicate detection on the stage 1 output, by filter block
stage2_seed_df = handler.load_csv(STAGE1_CSV)
stage2_results = handler.run_stage2_blocks(stage2_seed_df)

handler.export_stage2_csv(stage2_results, STAGE2_CSV)
handler.generate_stage2_report(stage2_seed_df, stage2_results, STAGE2_MD, STAGE2_CSV)
