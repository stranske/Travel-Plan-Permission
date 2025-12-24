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
