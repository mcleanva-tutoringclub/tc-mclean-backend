#!/usr/bin/env python3
"""
Download ONLY the link tables between objects (Student <-> Pipeline), then rebuild every
readable / required file so the "Linked ..." columns are filled. READ ONLY, ~25 API calls.
get_students.py and get_pipelines.py also do this automatically.

    python get_relationships.py
"""
import os
import sys

from ontraport_common import (HERE, LINKABLE, Logger, PermissionDenied, ReadOnlyViolation,
                              export_junctions, load_env, make_client, rebuild_from_disk)


def main():
    load_env()
    root = os.path.join(HERE, "export_data")
    os.makedirs(os.path.join(root, "relationships"), exist_ok=True)
    log = Logger(os.path.join(root, "relationships", "relationships_export.log"))
    client = make_client(log)
    log("=== relationships: export started - READ ONLY ===")
    s = export_junctions(client, root, 10000, log)
    for label in LINKABLE.values():
        if os.path.exists(os.path.join(root, label, "raw", f"{label}.json")):
            log(f"[refresh] rebuilding {label} files (no API calls)")
            rebuild_from_disk(root, label, log, quiet=True)
    log(f"=== relationships: {s['status']} - {client.calls} API calls ===")


if __name__ == "__main__":
    try:
        main()
    except (ReadOnlyViolation, PermissionDenied) as e:
        sys.exit(f"STOPPED: {e}")
