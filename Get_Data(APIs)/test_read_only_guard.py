#!/usr/bin/env python3
"""
Proves the exporter cannot write to Ontraport. Runs fully OFFLINE - the network is
disabled for the test, so if any request were attempted the test would fail.

    python test_read_only_guard.py
"""
import sys
import urllib.request

import ontraport_common as oc

attempted = []


def no_network(req, *a, **k):
    attempted.append((req.get_method(), req.full_url))
    raise ConnectionAbortedError("test: network disabled")


urllib.request.urlopen = no_network
client = oc.ReadOnlyClient("test-key", "test-app", max_rpm=600, reserve=0, log=lambda m: None)

must_block = {
    "POST create object":           lambda: client.post("objects", {"objectID": 0, "firstname": "x"}),
    "PUT update object":            lambda: client.put("objects", {"objectID": 0, "id": 1}),
    "PATCH":                        lambda: client.patch("objects"),
    "DELETE single":                lambda: client.delete("object", {"objectID": 0, "id": 1}),
    "DELETE many":                  lambda: client.delete("objects", {"objectID": 0, "ids": "0"}),
    "generic request('POST')":      lambda: client.request("POST", "objects"),
    "generic request('delete')":    lambda: client.request("delete", "objects"),
    "GET on tag endpoint":          lambda: client.get("objects/tag", {"objectID": 0}),
    "GET on sequence endpoint":     lambda: client.get("objects/sequence"),
    "GET on fieldeditor":           lambda: client.get("objects/fieldeditor", {"objectID": 0}),
    "GET on unknown endpoint":      lambda: client.get("Contacts/saveorupdate"),
    "path trick ../":               lambda: client.get("../objects"),
}

failed = 0
for name, call in must_block.items():
    try:
        call()
        print(f"  FAIL  {name}: was NOT blocked")
        failed += 1
    except oc.ReadOnlyViolation:
        print(f"  ok    {name}: blocked")
    except ConnectionAbortedError:
        print(f"  FAIL  {name}: reached the network")
        failed += 1

if attempted:
    print(f"\nFAIL: {len(attempted)} write attempt(s) reached the network layer: {attempted}")
    failed += 1

# An allowed read must still go out - and only as GET.
try:
    client.get("objects/getInfo", {"objectID": 0})
except ConnectionAbortedError:
    pass
reads = [a for a in attempted if a[0] == "GET"]
if reads and all(m == "GET" for m, _ in attempted):
    print("  ok    allowed read (objects/getInfo) is sent as GET")
else:
    print("  FAIL  allowed read was not sent correctly")
    failed += 1

print("\nRESULT:", "ALL CHECKS PASSED - exporter is read-only" if not failed else f"{failed} CHECK(S) FAILED")
sys.exit(1 if failed else 0)
