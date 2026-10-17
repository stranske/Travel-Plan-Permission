"""Prove the foreign-replay gate detects removal of production authorization."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
SOURCE = ROOT / "src/travel_plan_permission/portal_receipt_store.py"
GUARD = """            if draft.receipt_binding is not None:
                if auth_context is None:
                    raise HTTPException(status_code=404, detail="Portal receipt not found.")
                authorize_draft_owner(draft, auth_context)
"""


def run(name):
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/python/test_portal_receipt_api.py",
        "-k",
        "test_foreign_overwrite_cannot_replace_bound_execution",
        "-q",
        "--junitxml=" + str(EVIDENCE / (name + ".xml")),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    (EVIDENCE / (name + ".log")).write_text(result.stdout + result.stderr)
    return {"argv": command, "returncode": result.returncode}


original = SOURCE.read_bytes()
assert original.decode().count(GUARD) == 1
try:
    SOURCE.write_text(original.decode().replace(GUARD, "", 1))
    red = run("owner-check-red")
finally:
    SOURCE.write_bytes(original)
assert SOURCE.read_bytes() == original
green = run("owner-check-restored")
receipt = {
    "source": str(SOURCE.relative_to(ROOT)),
    "restored_sha256": hashlib.sha256(original).hexdigest(),
    "byte_identical_restoration": True,
    "mutation": "remove the bound-execution owner authorization from preserve_bound_submission",
    "red": red,
    "restored": green,
}
(EVIDENCE / "owner-check-mutation.json").write_text(json.dumps(receipt, indent=2) + "\n")
assert red["returncode"] == 1 and green["returncode"] == 0, receipt
