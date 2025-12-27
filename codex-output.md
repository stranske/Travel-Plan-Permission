Wired markdownlint-cli2 to use the repo’s `.markdownlint.yaml` so the lint run respects the project rule set and should let `docs/policy-api.md` pass under the intended configuration. This change is in `.markdownlint-cli2.yaml`, keeping the ignore patterns intact while adding the shared config reference.

Tests: could not run `markdownlint-cli2` because npm has no cached package and network access is restricted (`npm exec --offline -- markdownlint-cli2 docs/policy-api.md` fails with ENOTCACHED).

Next steps you can take:
1. `npm ci`
2. `npx markdownlint-cli2 "docs/policy-api.md"`