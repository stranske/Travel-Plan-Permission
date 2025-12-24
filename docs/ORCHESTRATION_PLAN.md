mkdir -p docs
cat > docs/ORCHESTRATION_PLAN.md <<'EOF'
# Travel-Plan-Permission: Orchestration & Agent Plan

## 1. Overview

This document describes how the Travel-Plan-Permission policy engine will integrate with a LangGraph-based orchestration layer and a small set of LLM agents to support end-to-end travel workflows.

The system has two main goals:

1. **Long-term**: Provide a full pre-trip and post-trip experience, including planning, policy checking, approvals, and reconciliation.
2. **Short-term (early deliverable)**: Provide an automated way to fill the organization’s existing travel request spreadsheet template from a finalized trip plan so users can benefit before the full stack is deployed.

The orchestration layer will use **LangGraph** to coordinate deterministic policy logic (this repo), LLM agents, and user/supervisor interactions.

---

## 2. Components and Responsibilities

### 2.1 Policy Engine (this repo)

- Encapsulates organizational travel policy.
- Provides deterministic functions for:
  - Plan compliance checks
  - Listing allowed vendors
  - Post-trip reconciliation
  - Filling the existing organizational spreadsheet template
- Exposes a stable Python API surface (see Section 4):
  - `check_trip_plan(plan: TripPlan) -> PolicyCheckResult`
  - `list_allowed_vendors(plan: TripPlan) -> list[str]`
  - `reconcile(plan: TripPlan, receipts: list[Receipt]) -> ReconciliationResult`
  - `fill_travel_spreadsheet(plan: TripPlan, output_path: Path) -> Path`

### 2.2 Orchestration Service (LangGraph)

- Maintains workflow state via a shared `TripState` model.
- Implements pre-trip and post-trip workflows as graphs.
- Calls the policy engine functions as deterministic nodes.
- Invokes LLM agents to:
  - Normalize user input into structured plans
  - Explain policy results
  - Summarize vendor options
  - Explain reconciliation outcomes

### 2.3 LLM Agents

- Reside as node functions in the orchestration service.
- Use OpenAI’s API to:
  - Transform free text into structured data (e.g., `TripPlan`)
  - Generate explanations and options
- Are not separate services; they are functions in the same process as LangGraph that call out to the LLM.

Examples:

- **Plan Normalization Agent**
  - Reads raw user request.
  - Outputs a structured `TripPlan`.

- **Policy Explanation Agent**
  - Reads `TripPlan`, `PolicyCheckResult`.
  - Produces a user-facing explanation and suggested changes.

- **Option Summarization Agent**
  - Reads vendor search results.
  - Produces a small set of understandable choices.

- **Reconciliation Explanation Agent**
  - Reads reconciliation results.
  - Produces an explanation for user and supervisor.

### 2.4 User and Supervisor Interfaces

- Early phases: minimal CLI / simple web UI.
- Later phases: integrated app for:
  - Users to plan trips
  - Supervisors to review and approve requests and expenses

### 2.5 Storage and Audit

- Persistent storage of `TripState` for each trip/workflow.
- Logging of:
  - State transitions
  - Policy versions used
  - Supervisor decisions
- Support for retrospective analysis and audits.

---

## 3. Runtime Location of the Policy Engine

### 3.1 Phase 0–2: In-process Package

For initial phases, the policy engine will run as an **in-process Python package**:

- The orchestrator service (LangGraph) and this repo share a Python environment.
- The orchestrator imports and calls the policy API directly.
- No additional network or service infrastructure is required.

To support this:

- This repo will be made installable as a Python package (via `pyproject.toml` or `setup.py`).
- The public policy API will be defined in a dedicated module (e.g., `policy_api.py`).

### 3.2 Future Option: Internal Service

As the system matures, the policy engine may be wrapped as an internal service:

- A small HTTP/gRPC application exposing endpoints such as:
  - `/check_trip_plan`
  - `/list_allowed_vendors`
  - `/reconcile`
- Deployed as a container or service within organizational infrastructure.
- LangGraph nodes call the service using HTTP/gRPC clients.

The API shapes defined in this repo are designed to be serializable and service-friendly, so this transition is primarily an infrastructure decision and does not change the core logic.

---

## 4. Policy Engine API Surface (Step 1)

A stable API surface will be defined in a module such as `policy_api.py`.

### 4.1 Core models (sketch)

```python
from pydantic import BaseModel
from typing import List, Literal, Dict
from datetime import date

class TripPlan(BaseModel):
    traveler_name: str
    traveler_role: str
    department: str
    purpose: str

    origin_city: str
    destination_city: str
    departure_date: date
    return_date: date

    transportation_mode: Literal["air", "train", "car", "mixed"]
    expected_costs: Dict[str, float]
    funding_source: str
    # Additional fields as required by policy and spreadsheet

class PolicyIssue(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"]
    context: Dict[str, str]

class PolicyCheckResult(BaseModel):
    status: Literal["pass", "fail"]
    issues: List[PolicyIssue]
    policy_version: str

class Receipt(BaseModel):
    # Vendor, date, amount, category, etc.
    ...

class ReconciliationResult(BaseModel):
    # Classification of expenses vs plan
    ...

### 4.2 Core functions

def check_trip_plan(plan: TripPlan) -> PolicyCheckResult:
    ...

def list_allowed_vendors(plan: TripPlan) -> list[str]:
    ...

def reconcile(plan: TripPlan, receipts: list[Receipt]) -> ReconciliationResult:
    ...

def fill_travel_spreadsheet(plan: TripPlan, output_path: Path) -> Path:
    ...

## 5. Early Deliverable: Spreadsheet Auto-Fill

### 5.1 Goal

Provide an early, practical tool that:

  - Takes a finalized TripPlan as input.

  - Fills the existing organizational travel request spreadsheet template stored in this repo.

  - Outputs a completed Excel file that users can submit through existing processes.

This is valuable even before the full orchestration and UI are built and will later become a node in the pre-trip workflow.

### 5.2 Spreadsheet Writer Function (example)
from pathlib import Path
from openpyxl import load_workbook

TEMPLATE_PATH = Path(__file__).parent / "templates" / "travel_request_template.xlsx"

def fill_travel_spreadsheet(plan: TripPlan, output_path: Path) -> Path:
    wb = load_workbook(TEMPLATE_PATH)
    ws = wb.active  # or select by name

    # Map TripPlan fields to spreadsheet cells (example)
    ws["B2"] = plan.traveler_name
    ws["B3"] = plan.department
    ws["B4"] = plan.purpose

    ws["C6"] = plan.origin_city
    ws["D6"] = plan.destination_city
    ws["E6"] = plan.departure_date.strftime("%Y-%m-%d")
    ws["F6"] = plan.return_date.strftime("%Y-%m-%d")

    # Additional mappings as required by the template

    wb.save(output_path)
    return output_path

### 5.3 CLI or Script (example)

import json
import sys
from pathlib import Path

def main():
    if len(sys.argv) != 3:
        print("Usage: fill_spreadsheet plan.json output.xlsx")
        sys.exit(1)

    plan_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    plan_data = json.loads(plan_path.read_text())
    plan = TripPlan(**plan_data)

    filled_path = fill_travel_spreadsheet(plan, output_path)
    print(f"Created {filled_path}")

if __name__ == "__main__":
    main()

Later, this function (fill_travel_spreadsheet) will be used as a node in the LangGraph pre-trip workflow after the trip proposal has been finalized and approved.

## 6. Workflow Design with LangGraph

### 6.1 Shared State Model (sketch)

from typing import List, Dict, Optional, Literal
from pydantic import BaseModel

class TripState(BaseModel):
    trip_id: str
    user_id: str
    phase: Literal["pre_trip", "post_trip"]

    raw_user_request: Optional[str] = None
    normalized_trip_plan: Optional[dict] = None

    policy_status: Optional[Literal["pending", "pass", "fail"]] = None
    policy_issues: List[dict] = []
    policy_version: Optional[str] = None

    search_criteria: Optional[dict] = None
    vendor_results: Dict[str, list] = {}

    selected_options: Dict[str, dict] = {}

    supervisor_id: Optional[str] = None
    approval_status: Optional[Literal["pending", "approved", "rejected"]] = None
    approval_history: List[dict] = []

    receipts: List[dict] = []
    reconciliation_result: Optional[dict] = None

    # Fields populated by LLM agents
    policy_explanation_for_user: Optional[str] = None
    suggested_changes: Optional[dict] = None

This state is persisted so workflows can span multiple sessions and support audit.

### 6.2 Pre-Trip Workflow (Graph)

1. Initial Plan Capture
  - User describes trip.
  - Plan Normalization Agent converts free text into a TripPlan.
  - Saved into TripState.normalized_trip_plan.
2. Pre-check Policy
  - Node calls check_trip_plan(TripPlan).
  - Stores policy_status, policy_issues, policy_version.
3. Policy Explanation & Adjustment Loop
  - Policy Explanation Agent reads policy results and generates an explanation plus suggested changes.
  - User adjusts plan based on suggestions.
  - Loop until plan passes policy or user stops.
4. Vendor Search
  - Node uses list_allowed_vendors(plan) plus travel APIs to fetch options.
  - Stores vendor search results in vendor_results.
5. Option Summarization & Selection
  - Option Summarization Agent turns raw options into a manageable set of choices.
  - User selects preferred options.
  - Selections stored in selected_options.
6. Final Policy Check
  - Re-run check_trip_plan on final selected options.
  - Final safety check before generating artifacts.
7. Spreadsheet Generation (Early and Final Integration)
  - Node calls fill_travel_spreadsheet with the finalized TripPlan.
  - Outputs a completed Excel file.
  - This step is both:
    - An early deliverable (CLI), and
    - An integrated node in the full workflow.
8. Supervisor Approval
  - Supervisor views the plan and attached spreadsheet.
  - Approves or rejects.
  - Decision recorded in approval_status and approval_history.

### 6.3 Post-Trip Workflow (Graph)

1. Receipt Ingestion
  - User uploads or forwards receipts.
  - Stored in TripState.receipts.
2. Receipt Extraction
  - Node uses OCR/LLM to convert receipts into structured Receipt objects.
3. Reconciliation
  - Node calls reconcile(plan, receipts) from the policy engine.
  - Stores reconciliation_result.
4. Reconciliation Explanation
  - Reconciliation Explanation Agent generates a human-readable summary of:
    - Matches
    - Variances
    - Potential issues
5. Supervisor Expense Approval
  - Supervisor reviews reconciliation summary and decides.
  - Decision and rationale recorded in state.

## 7. LLM Agent Implementation Model

LLM agents are implemented as node functions in the orchestrator that:
1. Read the relevant subset of TripState.
2. Construct a prompt (and tools if needed).
3. Call the LLM via the OpenAI API.
4. Parse the result into structured output.
5. Update TripState and return it to LangGraph.

Example pattern for the Policy Explanation Agent:

from langchain_openai import ChatOpenAI
import json

policy_explainer_llm = ChatOpenAI(model="gpt-5.1")

def policy_explainer_agent(state: TripState) -> TripState:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a travel policy assistant. "
                "Given a structured trip plan and policy check result, "
                "explain any issues and suggest concrete compliant changes. "
                "Respond in JSON with keys 'explanation' and 'suggested_changes'."
            ),
        },
        {
            "role": "user",
            "content": json.dumps({
                "trip_plan": state.normalized_trip_plan,
                "policy_status": state.policy_status,
                "policy_issues": state.policy_issues,
            }),
        },
    ]

    response = policy_explainer_llm.invoke(messages)
    try:
        data = json.loads(response.content)
    except json.JSONDecodeError:
        state.policy_explanation_for_user = response.content
        return state

    state.policy_explanation_for_user = data.get("explanation")
    state.suggested_changes = data.get("suggested_changes")
    return state

The agent “resides” in the same Python application that runs LangGraph. The only remote aspect is the call to the LLM endpoint.

Similar patterns will be used for:
  - Plan Normalization Agent
  - Option Summarization Agent
  - Reconciliation Explanation Agent

## 8. Implementation Phases

### Phase 0: Policy Engine Stabilization
  - Define TripPlan, PolicyIssue, PolicyCheckResult, Receipt, and ReconciliationResult in policy_api.py.
  - Implement:
    - check_trip_plan
    - list_allowed_vendors
    - reconcile
  - Add tests for key policy scenarios.
  - Make the repo installable as a Python package.

### Phase 1: Spreadsheet Auto-Fill (Early Deliverable)
  - Implement fill_travel_spreadsheet(plan: TripPlan, output_path: Path).
  - Create a CLI tool that:
    - Reads a JSON representation of TripPlan.
    - Fills the spreadsheet template.
    - Outputs a completed Excel file.
  - Document how users can:
    - Create a plan.json manually or via a small helper.
    - Run the command to generate the spreadsheet.

### Phase 2: Orchestration Skeleton
  - Create a separate orchestrator module/project.
  - Define TripState.
  - Implement minimal LangGraph workflow:
    - precheck_policy_node
    - vendor_search_node (stub or prototype)
    - final_policy_check_node
  - Add a CLI that:
    - Creates a sample TripPlan
    - Wraps it in TripState
    - Runs the graph and prints the result.

### Phase 3: Pre-Trip Workflow with Agents
  - Implement Plan Normalization Agent.
  - Implement Policy Explanation Agent and plan adjustment loop.
  - Implement Option Summarization Agent.
  - Integrate vendor search with approved travel providers.
  - Integrate the spreadsheet generation node into the workflow.

### Phase 4: Supervisor Approval
  - Add supervisor approval logic to the pre-trip graph.
  - Provide a minimal UI or API for supervisors to review and approve.
  - Persist approval decisions and policy version for audit.

### Phase 5: Post-Trip Reconciliation
  - Implement receipt ingestion and extraction.
  - Implement reconcile integration in the post-trip graph.
  - Implement Reconciliation Explanation Agent.
  - Add supervisor approval for expenses.

### Phase 6: Hardening and Service Evolution
  - Improve logging, metrics, and error handling.
  - Consider exposing the policy engine as an internal service if needed.
  - Tighten identity and access control around user and supervisor actions.
  - Extend policy logic as required by stakeholders.
