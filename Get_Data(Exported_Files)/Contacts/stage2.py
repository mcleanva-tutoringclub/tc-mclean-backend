import handler

SEED_CSV = '1stage_Filtered_Column_with_note.csv'
OUTPUT_CSV = '2stage_Duplicates_by_Block.csv'
OUTPUT_MD = '2stage_Duplicates_by_Block.md'

df = handler.load_csv(SEED_CSV)
results = handler.run_stage2_blocks(df)

handler.export_stage2_csv(results, OUTPUT_CSV)
handler.generate_stage2_report(df, results, OUTPUT_MD, OUTPUT_CSV)
