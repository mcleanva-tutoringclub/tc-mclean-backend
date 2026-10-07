#!/usr/bin/env python3
"""
ONE COMMAND for everything pipeline-related. READ ONLY - GET requests only.

    python get_pipelines.py            # fresh download (continues instead if the last run was interrupted)
    python make_readable.py pipelines    # rebuild only the readable file - no API calls

Steps (all automatic): all Pipelines (custom object 10002 "oPipeline" = leads / sales state) with every field -> raw/;
staff + tag lists -> lookups/; every note attached to a pipeline -> notes/;
pipelines_readable.csv with labels, readable dates and the note columns after "Last Note".

Output: export_data/pipelines/  (pipelines_readable.csv, summary, log, raw/, notes/, lookups/)
"""
from ontraport_common import export_full

OBJECT_ID = 10002
LABEL = "pipelines"

if __name__ == "__main__":
    export_full(OBJECT_ID, LABEL)
