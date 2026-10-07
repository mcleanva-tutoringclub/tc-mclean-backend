Columns to keep in the "<object>_required.csv" file, one name per line, in the order you want.
Names are the column headers of <object>_readable.csv.

contacts.txt  - the 151 required contact columns (2 Oct 2026)
students.txt  - the 460 client-approved student columns (5 Oct 2026)
pipelines.txt - the 132 required pipeline columns (3 Oct 2026)

Edit a list, then rebuild without any API calls:   python make_readable.py contacts
