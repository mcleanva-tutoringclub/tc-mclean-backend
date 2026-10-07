#!/usr/bin/env python3
"""
ONE COMMAND for everything student-related. READ ONLY - GET requests only.

    python get_students.py            # fresh download (continues instead if the last run was interrupted)
    python make_readable.py students    # rebuild only the readable file - no API calls

Steps (all automatic): all Students (custom object 10000 "oStudents") with every field -> raw/;
staff + tag lists -> lookups/; every note attached to a student -> notes/;
students_readable.csv with labels, readable dates and the note columns after "Last Note".

Students has ~540 fields, so each page is fetched in several field chunks and merged.
If you get error 400/414:  python get_students.py --chunk 80
NOTE: contains school-portal passwords and health information - keep the output private.

Output: export_data/students/  (students_readable.csv, summary, log, raw/, notes/, lookups/)
"""
from ontraport_common import export_full

OBJECT_ID = 10000
LABEL = "students"

if __name__ == "__main__":
    export_full(OBJECT_ID, LABEL)
