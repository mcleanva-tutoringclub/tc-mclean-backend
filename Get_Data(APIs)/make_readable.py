#!/usr/bin/env python3
"""
OFFLINE - no API calls. Rebuilds the readable / required files from what is already
downloaded, including the "Linked ..." columns between contacts, pipelines and students.
Use it after changing a required_columns list, the divider or the timezone.

    python make_readable.py             # every object already downloaded
    python make_readable.py contacts    # just one
"""
import os
import sys

from ontraport_common import HERE, LINKABLE, load_env, rebuild_from_disk


def main():
    load_env()
    root = os.path.join(HERE, "export_data")
    labels = sys.argv[1:] or [l for l in LINKABLE.values() if os.path.isdir(os.path.join(root, l, "raw"))]
    for label in labels:
        print(f"--- {label}")
        rebuild_from_disk(root, label, print)


if __name__ == "__main__":
    main()
