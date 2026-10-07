"""
Shared helper for the TC McLean Ontraport export scripts.

READ-ONLY: this module can only send HTTP GET requests. Nothing in Ontraport is changed.

Safety limits (all configurable in .env):
  ONTRAPORT_MAX_RPM   max requests per minute this script will send       (default 90)
  ONTRAPORT_RESERVE   pause when Ontraport reports this many calls left   (default 60)
Ontraport's account limit is 180/min and is SHARED with Make.com and website forms,
so the defaults use at most half of it and always leave headroom for live integrations.

Resume: progress is saved after every page. If a run stops (network, Ctrl+C), run the
same script again and it continues from the last saved record. Use --fresh to restart.
"""
import argparse
import csv
from collections import defaultdict
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BASE_URL = "https://api.ontraport.com/1/"
PAGE_SIZE = 50  # Ontraport maximum per request
HERE = os.path.dirname(os.path.abspath(__file__))

# Read-only enforcement. Anything outside these lists raises ReadOnlyViolation
# BEFORE a request is built or sent.
ALLOWED_METHODS = frozenset({"GET"})
ALLOWED_ENDPOINTS = frozenset({
    "objects/meta",     # field definitions
    "objects/getInfo",  # record counts
    "objects",          # list records
    "object",           # single record
})


class ReadOnlyViolation(RuntimeError):
    """Raised when code tries to send anything other than an allowed read request."""


class PermissionDenied(RuntimeError):
    """Ontraport answered 401/403: the API key may not read this object."""

    def __init__(self, code, object_id):
        self.code, self.object_id = code, object_id
        super().__init__(f"Ontraport refused access ({code}) to object {object_id} - "
                         f"the API key has no permission to read it.")


# ----------------------------------------------------------------------------- config
def load_env(path=os.path.join(HERE, ".env")):
    """Minimal .env reader (KEY=VALUE lines). Real environment variables win."""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].split("\t#", 1)[0]  # allow trailing comments
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Logger:
    def __init__(self, path):
        self.fh = open(path, "a", encoding="utf-8")

    def __call__(self, msg):
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
        print(line, flush=True)
        self.fh.write(line + "\n")
        self.fh.flush()


# ----------------------------------------------------------------------------- client
class ReadOnlyClient:
    """GET-only Ontraport client with a hard requests-per-minute cap.

    Read-only is ENFORCED, not just intended - three independent checks, all before
    anything touches the network:
      1. post/put/patch/delete methods exist only to raise ReadOnlyViolation.
      2. Every request is checked against ALLOWED_METHODS and ALLOWED_ENDPOINTS.
      3. The final urllib Request object is re-checked right before it is sent.
    A violation is logged and stops the script; no API call is made.
    """

    def __init__(self, api_key, app_id, max_rpm, reserve, log):
        self.headers = {"Api-Key": api_key, "Api-Appid": app_id, "Accept": "application/json"}
        self.min_interval = 60.0 / max_rpm
        self.reserve = reserve
        self.log = log
        self.last_call = 0.0
        self.calls = 0

    # --- guard 1: write methods are blocked outright -------------------------------
    def post(self, path, *a, **k):
        self._block("POST", path)

    def put(self, path, *a, **k):
        self._block("PUT", path)

    def patch(self, path, *a, **k):
        self._block("PATCH", path)

    def delete(self, path, *a, **k):
        self._block("DELETE", path)

    def request(self, method, path, params=None, **k):
        """Generic entry point - only GET gets through."""
        self._check(method, path)
        return self.get(path, params)

    def _block(self, method, path):
        msg = (f"BLOCKED: attempted {method} {path}. This exporter is read-only; "
               f"create/update/delete calls are not allowed. No request was sent.")
        self.log(msg)
        raise ReadOnlyViolation(msg)

    # --- guard 2: method + endpoint allowlist --------------------------------------
    def _check(self, method, path):
        method = str(method).upper()
        endpoint = path.strip("/").split("?", 1)[0]
        if method not in ALLOWED_METHODS:
            self._block(method, path)
        if endpoint not in ALLOWED_ENDPOINTS:
            msg = (f"BLOCKED: endpoint '{endpoint}' is not on the read-only allowlist "
                   f"{sorted(ALLOWED_ENDPOINTS)}. No request was sent.")
            self.log(msg)
            raise ReadOnlyViolation(msg)

    def get(self, path, params=None, retries=6):
        self._check("GET", path)
        url = BASE_URL + path.lstrip("/")
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(retries):
            # 1) our own pace: never faster than max_rpm
            wait = self.min_interval - (time.time() - self.last_call)
            if wait > 0:
                time.sleep(wait)
            self.last_call = time.time()
            req = urllib.request.Request(url, headers=self.headers, method="GET")
            # --- guard 3: last check on the exact request about to be sent -----------
            if req.get_method() != "GET" or req.data is not None or not url.startswith(BASE_URL):
                self._block(req.get_method(), path)
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    self.calls += 1
                    self._respect_headers(resp.headers)
                    body = resp.read().decode("utf-8")
                    return json.loads(body) if body else {}
            except urllib.error.HTTPError as e:
                self.calls += 1
                if e.code == 429:
                    pause = int(e.headers.get("X-Rate-Limit-Reset") or 60) + 2
                    self.log(f"  Ontraport says rate limit reached - waiting {pause}s")
                    time.sleep(pause)
                    continue
                if e.code in (401, 403):
                    raise PermissionDenied(e.code, (params or {}).get("objectID"))
                if e.code >= 500 and attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return {"_error": e.code, "_body": e.read().decode("utf-8", "replace")[:500]}
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < retries - 1:
                    self.log(f"  network problem ({e}) - retrying")
                    time.sleep(2 ** attempt)
                    continue
                return {"_error": "network", "_body": str(e)}
        return {"_error": "retries_exhausted"}

    def _respect_headers(self, headers):
        # 2) Ontraport's own counter for the whole account (includes Make.com etc.)
        try:
            remaining = int(headers.get("X-Rate-Limit-Remaining", "999"))
            reset = int(headers.get("X-Rate-Limit-Reset", "0"))
        except ValueError:
            return
        if remaining <= self.reserve:
            self.log(f"  account has {remaining} calls left this minute - pausing {reset + 1}s "
                     f"to leave room for live integrations")
            time.sleep(reset + 1)


# ----------------------------------------------------------------------------- export
def make_client(log):
    load_env()
    key, app = os.environ.get("ONTRAPORT_API_KEY"), os.environ.get("ONTRAPORT_APP_ID")
    if not key or not app:
        raise SystemExit("Missing credentials. Copy .env.example to .env and fill in "
                         "ONTRAPORT_API_KEY and ONTRAPORT_APP_ID.")
    return ReadOnlyClient(key, app,
                          max_rpm=float(os.environ.get("ONTRAPORT_MAX_RPM", 90)),
                          reserve=int(os.environ.get("ONTRAPORT_RESERVE", 60)),
                          log=log)


def eq(field, value):
    return {"field": {"field": field}, "op": "=", "value": {"value": value}}


def get_count(client, object_id, condition=None):
    params = {"objectID": object_id}
    if condition:
        params["condition"] = json.dumps(condition)
    r = client.get("objects/getInfo", params)
    if "_error" in r:
        raise SystemExit(f"Could not read record count for object {object_id}: {r}")
    return int((r.get("data") or {}).get("count") or 0)


def get_fields(client, object_id):
    r = client.get("objects/meta", {"objectID": object_id, "format": "byId"})
    if "_error" in r:
        raise SystemExit(f"Could not read field metadata for object {object_id}: {r}")
    data = r.get("data") or {}
    obj = data.get(str(object_id)) or next(iter(data.values()), {})
    return obj.get("name", str(object_id)), obj.get("fields", {})


def fetch_page(client, object_id, after_id, fields, extra_condition=None):
    """Keyset pagination (id > after_id, sorted by id): no skipped or duplicated records
    even if staff add records while the export runs."""
    cond = [{"field": {"field": "id"}, "op": ">", "value": {"value": after_id}}]
    for c in extra_condition or []:
        cond += ["AND", c]
    return client.get("objects", {
        "objectID": object_id,
        "range": PAGE_SIZE,
        "sort": "id",
        "sortDir": "asc",
        "condition": json.dumps(cond),
        "listFields": ",".join(fields),
    })


def fetch_all_offset(client, object_id, fields, log, max_records=20000):
    """start/range paging for SMALL reference objects (staff, tags) whose id field
    is not always called 'id'."""
    rows, start = [], 0
    while start < max_records:
        r = client.get("objects", {"objectID": object_id, "start": start, "range": PAGE_SIZE,
                                   "listFields": ",".join(fields)})
        if "_error" in r:
            log(f"  ERROR reading object {object_id} at offset {start}: {r['_error']} {r.get('_body', '')[:200]}")
            return rows, False
        batch = r.get("data") or []
        rows += batch
        if len(batch) < PAGE_SIZE:
            return rows, True
        start += PAGE_SIZE
    return rows, False


def read_jsonl(path):
    records, seen = [], set()
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                rec = json.loads(line)
                if str(rec.get("id")) not in seen:
                    seen.add(str(rec.get("id")))
                    records.append(rec)
    records.sort(key=lambda r: int(r["id"]))
    return records


def write_raw_csv(path, records, fields_meta):
    keys = ["id"] + [k for k in fields_meta if k != "id"]
    keys += sorted({k for r in records for k in r} - set(keys))
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:  # utf-8-sig opens cleanly in Excel
        w = csv.writer(fh)
        w.writerow([f"{fields_meta.get(k, {}).get('alias', k)} [{k}]" for k in keys])
        for r in records:
            w.writerow(["" if r.get(k) is None else r.get(k) for k in keys])


def export_records(client, object_id, name, out_dir, log, chunk=150, fresh=False, extra_condition=None):
    """Pull every record of one object (optionally filtered) with every field.
    Resumable: progress is checkpointed per page in <name>.jsonl.
    Writes <name>.json, <name>.csv (raw values) and <name>_fields.json into out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    jsonl = os.path.join(out_dir, f"{name}.jsonl")
    done_marker = os.path.join(out_dir, f"{name}.complete")
    # Resume ONLY an interrupted download. If the last download finished, take a fresh copy,
    # so edits made in Ontraport since then are included (migration data must be current).
    if os.path.exists(done_marker) and not fresh:
        log(f"[{name}] last download was complete - taking a fresh copy so recent Ontraport changes are included")
        fresh = True
    if fresh:
        for p in (jsonl, done_marker):
            if os.path.exists(p):
                os.remove(p)

    obj_name, fields_meta = get_fields(client, object_id)
    json.dump(fields_meta, open(os.path.join(out_dir, f"{name}_fields.json"), "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)
    expected = get_count(client, object_id, extra_condition)
    field_keys = [k for k in fields_meta if k != "id"]
    chunks = [["id"] + field_keys[i:i + chunk] for i in range(0, len(field_keys), chunk)] or [["id"]]
    est = -(-expected // PAGE_SIZE) * len(chunks)
    log(f"[{name}] Ontraport object '{obj_name}' ({object_id}): {expected} records, {len(fields_meta)} fields, "
        f"{len(chunks)} request(s) per page -> about {est} calls (~{est * client.min_interval / 60:.1f} min)")

    done_records = read_jsonl(jsonl)
    after_id = max((int(r["id"]) for r in done_records), default=0)
    done = len(done_records)
    if done:
        log(f"[{name}] resuming: {done} already saved, continuing after id {after_id}")

    errors = []
    with open(jsonl, "a", encoding="utf-8") as out:
        while True:
            page, ids, failed = {}, None, False
            for ci, fields in enumerate(chunks):
                r = fetch_page(client, object_id, after_id, fields, extra_condition)
                if "_error" in r:
                    log(f"[{name}] ERROR after id {after_id}, field chunk {ci + 1}: {r['_error']} {r.get('_body', '')[:200]}")
                    errors.append({"after_id": after_id, "chunk": ci + 1, **r})
                    failed = True
                    break
                rows = r.get("data") or []
                if ci == 0:
                    ids = [int(x["id"]) for x in rows]
                for row in rows:
                    if int(row["id"]) in ids:
                        page.setdefault(int(row["id"]), {}).update(row)
            if failed:
                log(f"[{name}] stopped on an error - nothing partial was saved. Run again to resume "
                    f"(or lower --chunk if it says 400/414).")
                break
            for rid in sorted(page):  # write the page only when every field chunk succeeded
                out.write(json.dumps(page[rid], ensure_ascii=False) + "\n")
            out.flush()
            done += len(page)
            if ids:
                after_id = max(ids)
            if done % 500 < PAGE_SIZE or len(ids) < PAGE_SIZE:
                log(f"[{name}]   {done} / {expected} saved")
            if len(ids) < PAGE_SIZE:
                break

    records = read_jsonl(jsonl)
    json.dump(records, open(os.path.join(out_dir, f"{name}.json"), "w", encoding="utf-8"), ensure_ascii=False)
    write_raw_csv(os.path.join(out_dir, f"{name}.csv"), records, fields_meta)
    complete = not errors and len(records) >= expected
    if complete:
        open(done_marker, "w").write(datetime.now().isoformat(timespec="seconds"))
    log(f"[{name}] {len(records)} of {expected} exported - {'COMPLETE' if complete else 'INCOMPLETE'}")
    return records, fields_meta, {"step": name, "object_id": object_id, "ontraport_count": expected,
                                  "exported": len(records), "fields": len(fields_meta),
                                  "status": "COMPLETE" if complete else "INCOMPLETE", "errors": errors}


# ----------------------------------------------------------------------------- related data
LOOKUPS = {
    "staff": {"object_id": 2, "key": "id", "fields": ["id", "firstname", "lastname", "email", "status"],
              "name": lambda r: " ".join(x for x in (r.get("firstname"), r.get("lastname")) if x).strip()},
    "tags": {"object_id": 14, "key": "tag_id", "fields": ["tag_id", "tag_name", "object_type_id"],
             "name": lambda r: r.get("tag_name") or ""},
}
# Automation (campaign) names behind the "Automations" column
LOOKUPS["campaigns"] = {"object_id": 140, "key": "id", "fields": ["id", "name"],
                        "name": lambda r: r.get("name") or ""}
# Tracking lists behind the UI's "First/Last Campaign/Lead Source/Medium/Content/Term Name" columns
for _oid, _label in ((75, "tracking_campaign"), (76, "tracking_lead_source"), (77, "tracking_medium"),
                     (78, "tracking_content"), (79, "tracking_term")):
    LOOKUPS[_label] = {"object_id": _oid, "key": "id", "fields": ["id", "name"],
                       "name": lambda r: r.get("name") or ""}


def export_lookups(client, out_dir, log):
    """Staff (owner / note author names) and Tags (tag names). A few calls."""
    os.makedirs(out_dir, exist_ok=True)
    result, ok_all, skipped = {}, True, []
    for label, cfg in LOOKUPS.items():
        try:
            rows, ok = fetch_all_offset(client, cfg["object_id"], cfg["fields"], log)
        except PermissionDenied as e:
            log(f"[lookups] {label}: SKIPPED - API key has no permission for object {cfg['object_id']} ({e.code}). "
                f"Those values stay as ids in the readable file; nothing else is affected.")
            skipped.append(label)
            result[label] = {}
            continue
        ok_all &= ok
        result[label] = {str(r.get(cfg["key"])): cfg["name"](r) for r in rows}
        with open(os.path.join(out_dir, f"{label}.csv"), "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=cfg["fields"], extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        log(f"[lookups] {label}: {len(rows)} rows{'' if ok else ' (INCOMPLETE)'}")
    json.dump(result, open(os.path.join(out_dir, "lookups.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    return result, {"step": "lookups", "staff": len(result.get("staff", {})), "tags": len(result.get("tags", {})),
                    "skipped_no_permission": skipped, "status": "COMPLETE" if ok_all else "INCOMPLETE"}


LINKABLE = {"0": "contacts", "10000": "students", "10002": "pipelines"}


def load_linked(root, object_id, fields_meta, lookups, tz, log):
    """Load other objects this one points to (e.g. pipeline -> Primary Contact -> contacts),
    from their own downloads in export_data/, so ids can be shown as names. Offline."""
    from ontraport_readable import LinkedObject
    wanted = {str(f.get("parent_object")) for f in fields_meta.values() if f.get("type") == "parent"}
    linked = {}
    for oid in sorted(wanted & set(LINKABLE)):
        if oid == str(object_id):
            continue
        lab = LINKABLE[oid]
        raw = os.path.join(root, lab, "raw")
        recs_path, flds_path = os.path.join(raw, f"{lab}.json"), os.path.join(raw, f"{lab}_fields.json")
        if not (os.path.exists(recs_path) and os.path.exists(flds_path)):
            log(f"[linked] {lab} not downloaded yet - run get_{lab}.py first so linked names can be filled in")
            continue
        recs = json.load(open(recs_path, encoding="utf-8"))
        flds = json.load(open(flds_path, encoding="utf-8"))
        when = datetime.fromtimestamp(os.path.getmtime(recs_path)).strftime("%Y-%m-%d %H:%M")
        linked[oid] = LinkedObject(lab, recs, flds, lookups, tz)
        log(f"[linked] using {len(recs)} {lab} downloaded {when} for names and copied {lab[:-1]} columns")
    return linked



# ----------------------------------------------------------------------------- relationships
OBJECT_ID_OF = {v: int(k) for k, v in {"0": "contacts", "10000": "students", "10002": "pipelines"}.items()}
# Link tables (many-to-many). Downloaded with either side; stored in export_data/relationships/
JUNCTIONS = {
    "student_pipeline_links": {"object_id": 10013, "a": ("f2141", "10000"), "b": ("f2140", "10002")},
}
JUNCTIONS_FOR = {"10000", "10002"}


def export_junctions(client, root, object_id, log):
    out_dir = os.path.join(root, "relationships")
    summary = {"step": "relationships", "status": "COMPLETE"}
    for name, j in JUNCTIONS.items():
        if str(object_id) not in (j["a"][1], j["b"][1]):
            continue
        try:
            _, _, s = export_records(client, j["object_id"], name, out_dir, log)
            summary[name] = s["exported"]
            if s["status"] != "COMPLETE":
                summary["status"] = "INCOMPLETE"
        except PermissionDenied as e:
            log(f"[relationships] {name}: SKIPPED - API key has no permission for object {j['object_id']} ({e.code})")
            summary[name] = "skipped - no permission"
    return summary


def _load_object(root, label):
    raw = os.path.join(root, label, "raw")
    rp, fp = os.path.join(raw, f"{label}.json"), os.path.join(raw, f"{label}_fields.json")
    if os.path.exists(rp) and os.path.exists(fp):
        return json.load(open(rp, encoding="utf-8")), json.load(open(fp, encoding="utf-8"))
    return None, None


def build_relations(root, object_id, lookups, tz, log):
    """'Linked ...' columns for this object, from the other downloads (offline):
       - other objects pointing here  (students/pipelines -> Primary Contact -> this contact)
       - link tables                  (student <-> pipeline)"""
    from ontraport_readable import LinkedObject
    me = str(object_id)
    relations = []
    for oid, lab in LINKABLE.items():
        if oid == me:
            continue
        recs, flds = _load_object(root, lab)
        if recs is None:
            continue
        lo = LinkedObject(lab, recs, flds, lookups, tz)
        pointers = [k for k, f in flds.items() if f.get("type") == "parent" and str(f.get("parent_object")) == me]
        for k in pointers:
            mapping = defaultdict(list)
            for r in recs:
                pid = str(r.get(k) or "")
                if pid not in ("", "0"):
                    mapping[pid].append((str(r.get("id")), lo.display_name(r)))
            name = lab.capitalize() if len(pointers) == 1 else f"{lab.capitalize()} ({flds[k].get('alias', k)})"
            relations.append((name, mapping))
            log(f"[relations] {name}: {sum(len(v) for v in mapping.values())} links from {lab} "
                f"'{flds[k].get('alias', k)}'")
    for name, j in JUNCTIONS.items():
        sides = {j["a"][1]: j["a"][0], j["b"][1]: j["b"][0]}
        if me not in sides:
            continue
        path = os.path.join(root, "relationships", f"{name}.json")
        if not os.path.exists(path):
            log(f"[relations] {name} not downloaded yet (comes with get_students.py / get_pipelines.py)")
            continue
        other_oid = next(o for o in sides if o != me)
        other_lab = LINKABLE[other_oid]
        recs, flds = _load_object(root, other_lab)
        lo = LinkedObject(other_lab, recs or [], flds or {}, lookups, tz)
        mapping = defaultdict(list)
        for row in json.load(open(path, encoding="utf-8")):
            mine, theirs = str(row.get(sides[me]) or ""), str(row.get(sides[other_oid]) or "")
            if mine in ("", "0") or theirs in ("", "0"):
                continue
            rec = lo.records.get(theirs)
            mapping[mine].append((theirs, lo.display_name(rec) if rec else f"{lo.label} {theirs} (not downloaded)"))
        relations.append((other_lab.capitalize(), mapping))
        log(f"[relations] {other_lab.capitalize()}: {sum(len(v) for v in mapping.values())} links from link table")
    return relations


def build_outputs(root, label, object_id, records, fields_meta, notes, notes_fields, lookups, tz, log):
    """readable + column check + required file. Offline. Returns (steps, readable path)."""
    from ontraport_readable import build_option_index, build_readable, column_check, read_column_list, select_columns
    base = os.path.join(root, label)
    other_fields = [_load_object(root, lab)[1] for lab in LINKABLE.values() if lab != label]
    option_index = build_option_index(fields_meta, *[f for f in other_fields if f])
    steps = []
    out_csv = os.path.join(base, f"{label}_readable.csv")
    linked = load_linked(root, object_id, fields_meta, lookups, tz, log)
    relations = build_relations(root, object_id, lookups, tz, log)
    r = build_readable(object_id, records, fields_meta, notes, notes_fields, lookups, tz, out_csv, linked, relations,
                       option_index)
    log(f"[readable] {r['records']} records x {r['columns']} columns -> {out_csv} ({r['with_notes']} have notes"
        + "".join(f"; {n} with linked {k.lower()}" for k, n in r["linked_counts"].items()) + ")")
    for w in r["warnings"]:
        log(f"[readable]   note: {w}")
    steps.append({"step": "readable", **{k: v for k, v in r.items() if k != "header"}, "status": "COMPLETE"})

    ui_file = os.path.join(HERE, "ui_columns", f"{label}.txt")
    if os.path.exists(ui_file):
        cc = column_check(r["header"], open(ui_file, encoding="utf-8").read().splitlines(),
                          os.path.join(base, f"{label}_column_check.csv"))
        log(f"[column check] Ontraport UI {cc['ui_columns']} columns vs export {cc['export_columns']}: "
            f"{cc['ui_only']} UI-only, {cc['export_only']} export-only -> {label}_column_check.csv")
        if cc["unexplained"]:
            log(f"[column check]   UNEXPLAINED UI columns (please check): {cc['unexplained']}")
        steps.append({"step": "column_check", **cc, "status": "COMPLETE"})

    req_file = os.path.join(HERE, "required_columns", f"{label}.txt")
    if os.path.exists(req_file):
        out_req = os.path.join(base, f"{label}_required.csv")
        rq = select_columns(out_csv, read_column_list(req_file), out_req)
        log(f"[required] {rq['records']} records x {rq['written']} of {rq['requested']} requested columns -> {out_req}")
        if rq["missing"]:
            log(f"[required]   NOT FOUND (check spelling in required_columns/{label}.txt): {rq['missing']}")
        steps.append({"step": "required", **rq,
                      "status": "COMPLETE" if not rq["missing"] else "COMPLETE - some columns not found"})
    return steps, out_csv


def rebuild_from_disk(root, label, log, quiet=False):
    """Rebuild one object's readable/required files from what is already downloaded. Offline."""
    from ontraport_readable import get_tz
    base = os.path.join(root, label)
    records, fields = _load_object(root, label)
    if records is None:
        log(f"skip {label}: nothing downloaded yet - run get_{label}.py first")
        return None
    load = lambda p, d=None: json.load(open(p, encoding="utf-8")) if os.path.exists(p) else d
    notes = load(os.path.join(base, "notes", f"{label}_notes.json"))
    notes_fields = load(os.path.join(base, "notes", f"{label}_notes_fields.json")) or \
        load(os.path.join(base, "notes", "all_notes_fields.json"), {})
    lookups = load(os.path.join(base, "lookups", "lookups.json"))
    tz, _ = get_tz()
    sink = (lambda m: None) if quiet else log
    steps, out_csv = build_outputs(root, label, OBJECT_ID_OF[label], records, fields, notes, notes_fields,
                                   lookups, tz, sink)
    if quiet:
        r = next(s for s in steps if s["step"] == "readable")
        log(f"[refresh]   {label}: {r['records']} records x {r['columns']} columns"
            + "".join(f", {n} with linked {k.lower()}" for k, n in r["linked_counts"].items()))
    return steps


NOTE_OBJECT_ID = 12


def export_notes_for(client, object_id, label, out_dir, log, fresh):
    """Only the notes that belong to this object type (e.g. contact notes for contacts).
    Notes link to records by object_type_id + contact_id (= the record's id)."""
    name = f"{label}_notes"
    total_notes = get_count(client, NOTE_OBJECT_ID)
    cond = [eq("object_type_id", object_id)]
    filtered = get_count(client, NOTE_OBJECT_ID, cond)
    log(f"[notes] account has {total_notes} notes in total; {filtered} are attached to {label} (object {object_id})")
    if filtered == 0 and total_notes > 0 and object_id == 0:
        # Older contact notes may have an empty object_type_id. Fall back to pulling all notes
        # and keeping those with object type 0 or empty.
        log("[notes] none matched object_type_id=0 - pulling all notes and filtering locally")
        records, fields_meta, summ = export_records(client, NOTE_OBJECT_ID, "all_notes", out_dir, log, fresh=fresh)
        keep = [n for n in records if str(n.get("object_type_id") or "0") == "0"]
        json.dump(keep, open(os.path.join(out_dir, f"{name}.json"), "w", encoding="utf-8"), ensure_ascii=False)
        write_raw_csv(os.path.join(out_dir, f"{name}.csv"), keep, fields_meta)
        summ.update({"step": name, "exported": len(keep), "note": "filtered locally from all notes"})
        return keep, fields_meta, summ
    return export_records(client, NOTE_OBJECT_ID, name, out_dir, log, fresh=fresh, extra_condition=cond)


# ----------------------------------------------------------------------------- one-command export
def export_full(object_id, label, client=None):  # noqa: C901
    """Everything for one object in one folder:
         export_data/<label>/raw/        all records, every field, raw values (the backup)
         export_data/<label>/notes/      notes attached to these records
         export_data/<label>/lookups/    staff + tag names
         export_data/<label>/<label>_readable.csv   readable values + note columns
         export_data/<label>/<label>_summary.json   counts + status per step
    """
    try:
        return _export_full(object_id, label, client)
    except PermissionDenied as e:
        print(f"\nSTOPPED: {e}\nCheck ONTRAPORT_API_KEY / ONTRAPORT_APP_ID in .env and that the key may read "
              f"this object (Ontraport > Administration > Integrations > API Key Manager).", file=sys.stderr)
        sys.exit(3)
    except ReadOnlyViolation as e:
        print(f"\nSTOPPED FOR SAFETY: {e}", file=sys.stderr)
        sys.exit(2)


def _export_full(object_id, label, client=None):
    ap = argparse.ArgumentParser(description=f"Export Ontraport {label} + notes + lookups (read only).")
    ap.add_argument("--out", default=os.path.join(HERE, "export_data"), help="output root folder")
    ap.add_argument("--chunk", type=int, default=int(os.environ.get("ONTRAPORT_FIELD_CHUNK", 150)),
                    help="fields per request; lower it (e.g. 80) if you get error 400/414")
    ap.add_argument("--fresh", action="store_true", help="ignore saved progress and download everything again")
    ap.add_argument("--skip-notes", action="store_true")
    args = ap.parse_args()

    load_env()
    from ontraport_readable import build_readable, column_check, get_tz, read_column_list, select_columns

    base = os.path.join(args.out, label)
    os.makedirs(base, exist_ok=True)
    log = Logger(os.path.join(base, f"{label}_export.log"))
    client = client or make_client(log)
    log(f"=== {label}: export started - READ ONLY ===")
    steps = []

    # 1. records
    records, fields_meta, s = export_records(client, object_id, label, os.path.join(base, "raw"), log,
                                             chunk=args.chunk, fresh=args.fresh)
    steps.append(s)

    # 2. lookups (staff, tags)
    lookups, s = export_lookups(client, os.path.join(base, "lookups"), log)
    steps.append(s)

    # 3. notes for this object
    notes, notes_fields = None, {}
    if not args.skip_notes:
        try:
            notes, notes_fields, s = export_notes_for(client, object_id, label, os.path.join(base, "notes"), log, args.fresh)
        except PermissionDenied as e:
            log(f"[notes] SKIPPED - API key has no permission to read Notes ({e.code}). "
                f"Ask the admin to tick Notes on the key, then run again.")
            notes, s = None, {"step": "notes", "status": "SKIPPED - no permission"}
        steps.append(s)

    # 4. link tables between objects (e.g. which students belong to which pipeline)
    if str(object_id) in JUNCTIONS_FOR:
        steps.append(export_junctions(client, args.out, object_id, log))

    # 5-7. readable file, column check, required file (no API calls)
    from ontraport_readable import get_tz
    tz, tz_name = get_tz()
    out_steps, out_csv = build_outputs(args.out, label, object_id, records, fields_meta, notes, notes_fields,
                                       lookups, tz, log)
    steps += out_steps

    # 8. refresh the OTHER objects' readable files so their "Linked ..." columns include this download
    for other in LINKABLE.values():
        if other != label and os.path.exists(os.path.join(args.out, other, "raw", f"{other}.json")):
            log(f"[refresh] rebuilding {other} files so they link to the new {label} data (no API calls)")
            rebuild_from_disk(args.out, other, log, quiet=True)

    ok = all(st.get("status") == "COMPLETE" for st in steps)
    json.dump({"object": label, "object_id": object_id, "finished_at": datetime.now().isoformat(timespec="seconds"),
               "api_calls_this_run": client.calls, "status": "COMPLETE" if ok else "INCOMPLETE - run again to resume",
               "steps": steps}, open(os.path.join(base, f"{label}_summary.json"), "w"), indent=1)
    log(f"=== {label}: {'COMPLETE' if ok else 'INCOMPLETE - run again, it resumes'} - {client.calls} API calls ===")
    log(f"Open: {out_csv}   (real family data - keep it private)")
    return ok


# ----------------------------------------------------------------------------- records only (students/pipelines for now)
def run(object_id, label, client=None):
    """Records only, no notes/lookups - used by get_students.py / get_pipelines.py until they
    are switched to export_full()."""
    try:
        ap = argparse.ArgumentParser(description=f"Export Ontraport {label} (object {object_id}) - read only.")
        ap.add_argument("--out", default=os.path.join(HERE, "export_data"))
        ap.add_argument("--chunk", type=int, default=int(os.environ.get("ONTRAPORT_FIELD_CHUNK", 150)))
        ap.add_argument("--fresh", action="store_true")
        args = ap.parse_args()
        load_env()
        out_dir = os.path.join(args.out, label)
        os.makedirs(out_dir, exist_ok=True)
        log = Logger(os.path.join(out_dir, f"{label}_export.log"))
        client = client or make_client(log)
        _, _, s = export_records(client, object_id, label, out_dir, log, chunk=args.chunk, fresh=args.fresh)
        json.dump(s, open(os.path.join(out_dir, f"{label}_summary.json"), "w"), indent=1)
        return s
    except PermissionDenied as e:
        print(f"\nSTOPPED: {e}", file=sys.stderr)
        sys.exit(3)
    except ReadOnlyViolation as e:
        print(f"\nSTOPPED FOR SAFETY: {e}", file=sys.stderr)
        sys.exit(2)
