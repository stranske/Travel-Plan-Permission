# Audit trail and validation snapshots

Validation snapshots provide a deterministic, tamper-evident record of each approval decision so past trips can be re-checked when policies change.

## Snapshot payload

Each snapshot is stored as a compact JSON document (`<trip_id>/<timestamp>.json`):

- `trip_id`: Identifier of the trip the validation was run against.
- `timestamp`: When the snapshot was captured (UTC ISO-8601).
- `policy_version`: Hash of the policy/rule set used for the run.
- `input_data`: Canonicalized trip plan data captured at validation time.
- `results[]`: Array of validation results (rule code, message, severity, blocking).
- `snapshot_hash`: Content hash of the snapshot payload.
- `previous_hash` / `chain_hash`: Hash chain fields that make the store append-only and tamper-evident.

## Capture points

- Snapshots are written whenever an approval decision is recorded (approved, rejected, flagged, or overridden) when a `ValidationSnapshotStore` is provided.
- Captures include the exact validation results used for the decision; if they are missing, the policy validator is run automatically before writing the snapshot.

## Storage and integrity

- Files are written immutably and chained by hash; any modification breaks the chain.
- Snapshots are serialized with compact separators and rejected if they exceed 10KB to keep typical audit entries lightweight.
- The comparison report (`compare_results`) highlights which rules changed between the original snapshot and a re-check under a new policy hash.
