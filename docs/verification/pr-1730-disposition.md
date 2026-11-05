# PR #1730 salvage disposition (issue #1727)

Source issue: #1727  
PR: #1730  
Tested head: `2611d73` (implementation at `6ac18ff` rebased onto `main`, plus this disposition record)  
Recorded: 2026-11-05

Salvaged scope: security-model documentation split, registered vs planned permission
maps in `security.py`, and regression tests in `test_http_service.py` /
`test_security_model.py`. Issue #1727 remains open for follow-up (`Refs #1727`).

## Focused regression (pass)

Command:

```text
/opt/anaconda3/bin/python3 -m pytest \
  tests/python/test_http_service.py::test_security_model_doc_lists_only_registered_api_routes \
  tests/python/test_http_service.py::test_api_endpoint_permissions_reference_only_registered_routes \
  tests/python/test_security_model.py -q
```

Exit code: 0

Observed:

```text
collected 15 items
tests/python/test_http_service.py ..                                     [ 13%]
tests/python/test_security_model.py .............                        [100%]
======================== 15 passed, 1 warning in 1.74s =========================
```

## Deliberate break → revert

Temporary edit: inserted `| \`GET /api/itineraries\` | \`view\` |` into the
**Implemented endpoint permissions** table in `docs/security-model.md` (file
restored byte-for-byte afterward).

Command:

```text
/opt/anaconda3/bin/python3 -m pytest \
  tests/python/test_http_service.py::test_security_model_doc_lists_only_registered_api_routes -q
```

Exit code: 1

Observed:

```text
AssertionError: implemented permission table lists unregistered paths: ['/api/itineraries']
```

Post-restore rerun of the same command: exit code 0, 1 passed.
