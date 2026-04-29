## Active opener checkpoint

- Automation: `pd-workloop-resume` (codex opener lane)
- Updated: `2026-04-29T15:13:29Z`
- Repo: `stranske/Travel-Plan-Permission`
- Source issue: `https://github.com/stranske/Travel-Plan-Permission/issues/996`
- Branch: `codex/issue-996-oidc-token-verification`
- Mode: `implementation-complete-local-validation-passed-ready-to-push`
- Discovery summary: priority-only fleet discovery selected the oldest high-priority eligible supported issue, Travel-Plan-Permission #996. Workflows #1976 was skipped as an ops credential alert. Manager-Database #906/#907 and Inv-Man-Intake #311 already have opener-owned PRs. The opener cap was 3/5 (`Manager-Database#945`, `Manager-Database#946`, `Inv-Man-Intake#349`), so this lane was allowed.
- Local checkout handling: canonical Dropbox checkout could not fetch (`.git/FETCH_HEAD: Operation not permitted`) and contained unrelated local state, so implementation was done in fresh synced clone `/tmp/tpp-996-JGEZAA/repo`.
- Implementation: added `TPP_AUTH_MODE=oidc` JWT/JWKS verification with 10-minute JWKS cache, issuer/audience/expiry/nbf/signature/kid validation, role mapping via `TPP_OIDC_ROLE_MAP`, readyz validation for `TPP_OIDC_AUDIENCE`, structured 401 bearer errors, PyJWT crypto dependency, and README/security-model docs.
- Validation: `python -m pytest tests/python/test_planner_auth.py tests/python/test_http_service.py -q` (64 passed); `python -m ruff check src/travel_plan_permission/planner_auth.py src/travel_plan_permission/http_service.py tests/python/test_planner_auth.py tests/python/test_http_service.py`; `python -m black --target-version py312 --check src/travel_plan_permission/planner_auth.py src/travel_plan_permission/http_service.py tests/python/test_planner_auth.py tests/python/test_http_service.py`.
- Next action: commit, push, open a draft PR labeled `agent:codex`, then record relay `pr_opened` and leave keepalive to handle CI/review.
