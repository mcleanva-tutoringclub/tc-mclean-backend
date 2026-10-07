#!/usr/bin/env python3
"""
One-time fix for ontraport_readable.py: decode multi-answer values like "152; 151"
(8a learning differences). Run it in the same folder as ontraport_readable.py:

    python patch_8a.py

Keeps a backup as ontraport_readable.py.bak. Makes no API calls. Safe to run twice.
"""
import os
import re
import shutil
import sys

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ontraport_readable.py")
MARK = "several answers in a single-choice field"

src = open(PATH, encoding="utf-8").read()
if MARK in src:
    sys.exit("Already patched - nothing to do. Run:  python make_readable.py students")

shutil.copy2(PATH, PATH + ".bak")

# 1. multi-select splitting: handle "152; 151" and "*/*152; 151*/*"
new_split = '''def split_multi(value):
    """Ontraport stores multi-select as */*1*/*2*/*; some imported records use "1; 2" instead."""
    text = str(value or "")
    out = []
    for part in MULTI_RE.split(text):           # */*1*/*2*/*  (also handles "*/*152; 151*/*")
        out += [x.strip() for x in part.split(";") if x.strip()]
    return out
'''
src, n1 = re.subn(r"def split_multi\(value\):\n(?:    .*\n|\n(?=    ))+", new_split, src, count=1)

# 2. single-choice dropdowns holding several valid answers
pattern = re.compile(
    r"( +)if str\(value\) in opts:\n\1    return opts\[str\(value\)\]\n\1return self\._foreign_or_raw\(key, str\(value\)\)")


def repl(m):
    i = m.group(1)
    return (f"{i}if str(value) in opts:\n{i}    return opts[str(value)]\n"
            f"{i}parts = split_multi(value)\n"
            f"{i}if len(parts) > 1 and all(p in opts for p in parts):  # {MARK}\n"
            f"{i}    return join_values(opts[p] for p in parts)\n"
            f"{i}return self._foreign_or_raw(key, str(value))")


src, n2 = pattern.subn(repl, src, count=1)

if n1 != 1 or n2 != 1:
    shutil.copy2(PATH + ".bak", PATH)
    sys.exit(f"Could not patch automatically (split={n1}, dropdown={n2}). Your file was left unchanged - "
             f"please replace ontraport_readable.py with the version from the latest zip instead.")

open(PATH, "w", encoding="utf-8").write(src)
compile(src, PATH, "exec")  # syntax check
print("Patched ontraport_readable.py (backup: ontraport_readable.py.bak).")
print("Now run:  python make_readable.py students")