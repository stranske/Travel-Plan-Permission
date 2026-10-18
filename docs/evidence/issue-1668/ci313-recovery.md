# Python 3.13 CI recovery

Hosted Gate run 39127207130 / job 117674815994 failed the XLSX restart test
at head 1419d995dd0c02e22ffe895912fb5b41bb5adcd2: the earlier review export
and the later real expense-download export had different timestamp-bearing ZIP
bytes. The expense route already regenerates its exports. Production generation
is unchanged. The test captures the actual artifact from the real exporter for
that request, then verifies the response bytes, filename and persisted event.
The exporter is invoked normally; no artifact payload is stubbed.

Repository-selected Python 3.12: `PYTHONPATH=src python -m pytest
tests/python/test_http_service.py -q`: 216 passed, 99.41 seconds. Black and Ruff
checks pass. Hosted Python 3.13 must rerun on the corrected head; local 3.13
execution is not claimed. Previous actual persistence-disconnect and exact-byte
restore proofs remain in this directory.
