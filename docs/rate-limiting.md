# Rate limiting strategy

The API layer should apply per-API-key rate limits with tiered budgets aligned to endpoint risk.

## Default tiers

| Tier | Requests | Window | Applies to |
| --- | --- | --- | --- |
| `standard` | 120 | 60s | `view`, `create` |
| `approval` | 60 | 60s | `approve` |
| `export` | 30 | 60s | `export` |
| `admin` | 20 | 60s | `configure` |

## Overrides

- Endpoint overrides should be applied for high-cost workloads (exports, audits).
- API key overrides should be reserved for trusted service accounts or partners.

## Scope

Rate limits are evaluated per API key and endpoint using a stable bucket key of
`{api_key}:{endpoint}`.
