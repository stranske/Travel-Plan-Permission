#!/usr/bin/env bash
set -euo pipefail

dependency_sha=$(git -C "${DEPENDENCY_PATH:?Reusable 13 must supply the dependency path}" rev-parse HEAD)
expected_sha=$(tr -d '[:space:]' < .github/trip-planner-pinned-ref)
if [[ "$dependency_sha" != "$expected_sha" ]]; then
  printf 'trip-planner pin mismatch: expected %s, resolved %s\n' "$expected_sha" "$dependency_sha" >&2
  exit 1
fi
printf 'host_resolved_sha=%s\npaired_dependency_sha=%s\n' "$(git rev-parse HEAD)" "$dependency_sha"

runtime=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/tpp-trip-planner.XXXXXXXX")
service_pid=
stop_service() {
  if [[ -n "$service_pid" ]]; then
    kill "$service_pid" 2>/dev/null || true
    wait "$service_pid" 2>/dev/null || true
    service_pid=
  fi
}
cleanup() {
  stop_service
  rm -r -- "$runtime"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

port=$(python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
export TPP_BASE_URL="http://127.0.0.1:$port"
export TPP_OIDC_PROVIDER=google TPP_AUTH_MODE=bootstrap-token
export TPP_PORTAL_STATE_PATH="$runtime/planner-state.sqlite3"
TPP_BOOTSTRAP_SIGNING_SECRET=$(python -c 'import secrets; print(secrets.token_hex(32))')
export TPP_BOOTSTRAP_SIGNING_SECRET
TPP_PLANNER_TOKEN=$(tpp-planner-token --subject ci-reusable-13-pilot)
TPP_MANAGER_TOKEN=$(tpp-planner-token --subject ci-reusable-13-pilot-manager --permission approve)
export TPP_PLANNER_TOKEN TPP_MANAGER_TOKEN
[[ -n "$TPP_PLANNER_TOKEN" && -n "$TPP_MANAGER_TOKEN" ]]

start_service() {
  tpp-planner-service --host 127.0.0.1 --port "$port" >>"$runtime/service.log" 2>&1 &
  service_pid=$!
  for _ in {1..30}; do
    kill -0 "$service_pid" 2>/dev/null || break
    if curl --fail --silent --max-time 1 "$TPP_BASE_URL/readyz" >/dev/null; then
      return 0
    fi
    sleep 1
  done
  printf 'Planner service did not become ready\n' >&2
  tail -n 20 "$runtime/service.log" >&2
  return 1
}

start_service
tpp-cross-repo-smoke --trip-planner-root "$DEPENDENCY_PATH" --receipt-output "$runtime/approved-receipt.json"
stop_service
start_service
tpp-cross-repo-smoke --verify-receipt "$runtime/approved-receipt.json"
printf 'TPP_TRIP_PLANNER_PILOT_OK\n'
