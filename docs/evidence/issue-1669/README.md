# Portal execution owner binding (#1669)

Generic writes now pass the authenticated server context into the serialized store operation. Existing portal execution linkage is resolved from persisted draft submission responses, not caller-provided draft IDs. Bound execution replays require the actual owner and an identical request and trip snapshot. Legacy unbound proposals remain supported.

Status/evaluation projections authorize the persisted owner under the same operation lock. Unavailable portal linkage fails closed; payload/version migration hints can deny access but cannot grant it. Portal retries recheck ownership inside the coordinated operation and preserve prior manager decisions.

`acceptance.log` and `acceptance.xml` record the two issue acceptance suites plus the existing module-size guard. `validation.json` binds actual production/test hashes and tool versions. `owner_check_mutation.py` removes the actual owner authorization, records three assertion failures (including unauthorized exact replay becoming HTTP 200), restores identical source bytes and records three passes. The modified-payload cases become HTTP 409 under the preexisting immutable-snapshot guard when ownership is removed; they do not demonstrate an overwrite of immutable snapshots on this already-hardened base.

`ruff.log` records the exact whole-tree CI command; `mypy.log` records production checks. Local Ruff/Mypy versions differ from hosted pins, so hosted CI remains a separate boundary. `complexity.log` is refreshed after committing because this guard uses committed changes. This proves local HTTP/auth/persistence behavior, not a deployed service, identity provisioning, or post-merge acceptance.
