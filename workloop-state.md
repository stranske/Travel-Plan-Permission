## 2026-05-31T05:04:57Z - opener (codex) issue #1128 materialization

- Repo: stranske/Travel-Plan-Permission
- Issue: #1128, "Reconcile ORCHESTRATION_PLAN.md with the implemented substrate - no LLM agents or vendor search exist"
- Branch: codex/issue-1128-orchestration-status
- Worktree: /Users/teacher/.codex/automations/pd-workloop-resume/worktrees/tpp-1128-orchestration-status
- Status: implemented locally; validation passed; next action is commit, push, open ready-for-review PR with agent:codex, agents:keepalive, and autofix labels.
- Implementation: updated docs/ORCHESTRATION_PLAN.md to remove stale generated shell wrapper text, add a machine-checkable Implementation Status table, mark LLM agents/vendor search/graph OCR as NOT IMPLEMENTED, list the built deterministic graph nodes, and document the future no-train/redaction/data-zone LLM boundary.
- Tests: added tests/python/test_docs_orchestration_status.py for the status table, the corrected agent wording, deterministic node names, and zero OpenAI client matches under src/.
- Validation:
  - python -m pytest tests/python/test_docs_orchestration_status.py -q
  - python -m ruff check tests/python/test_docs_orchestration_status.py
  - python -m black --check --fast tests/python/test_docs_orchestration_status.py
  - rg -n 'ChatOpenAI|langchain_openai|import openai' src/ returns no matches
  - git diff --check
