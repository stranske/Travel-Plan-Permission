# Provider governance

This package manages approved travel providers (airlines, hotels, and ground transport) through a
versioned registry stored at `config/providers.yaml`.

## Data model

- **Provider**: `name`, `type` (`airline`, `hotel`, `ground_transport`), `contract_id`,
  `valid_from`, `valid_to`, `destinations`, `rate_notes`.
- **Metadata**: `version`, `updated_at`, `approver`, and a `change_log` with
  `version`, `date`, `description`, and `approver` entries to make updates auditable.

Contracts must include both start and end dates so that lookups can filter to active providers.

## Workflow for updates

1. Propose the change (add/remove/update) in a PR and bump the `version` in `config/providers.yaml`.
2. Add a `change_log` entry with the new version, date, description, and the designated
   approver’s name or role.
3. Obtain approval from the designated approver recorded in the metadata before merging.
4. Run provider-related tests (`python -m pytest tests/python/test_providers.py`) to verify lookups.
5. Merge after approval so the audit trail reflects who authorized the change.

This workflow ensures the provider list is auditable, versioned, and controlled by a designated
approver.
