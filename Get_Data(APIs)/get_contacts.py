#!/usr/bin/env python3
"""
ONE COMMAND for everything contact-related. READ ONLY - GET requests only.

    python get_contacts.py            # fresh download (continues instead if the last run was interrupted)
    python make_readable.py contacts  # rebuild only the readable file - no API calls

Steps (all automatic):
  1. All Contacts (object 0 = family / guardian accounts), every field   -> raw/
  2. Staff + Tag lists, so Owner / Note Author / Tags show as names        -> lookups/
  3. Every note attached to a contact                                      -> notes/
  4. contacts_readable.csv: labels instead of IDs, readable dates, and the
     note columns (Note Count, All Notes, Note Author, Note Created Date,
     Note Date Modified, Note Type) right after "Last Note"               (no API calls)

Output folder:
  export_data/contacts/
    contacts_readable.csv     <- open this one
    contacts_summary.json     counts + status of every step
    contacts_export.log
    raw/      contacts.csv, contacts.json, contacts_fields.json   (untouched backup)
    notes/    contacts_notes.csv, contacts_notes.json
    lookups/  staff.csv, tags.csv, lookups.json
"""
from ontraport_common import export_full

OBJECT_ID = 0          # Ontraport "Contact"
LABEL = "contacts"

if __name__ == "__main__":
    export_full(OBJECT_ID, LABEL)
