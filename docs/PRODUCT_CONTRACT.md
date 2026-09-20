# Product contract — stranske/Travel-Plan-Permission
_First draft generated 2026-09-20 from the audit scorecard; the repo owns this file from now on. A PR that adds a user-facing route, command or page adds a line here. The audit's Phase 1.5 scores every line below and prints any surface not listed as UNSCORED._

## Purpose
Evaluate employer travel-policy compliance and drive traveller, exception, manager-review and export workflows.

## Primary journey
Create draft → submit for policy evaluation → request exception if needed → manager decides → traveller corrects/resubmits if requested → export approved artifacts.

## Core functions
| id | a <user> can … and sees … | entry point | probe (how to exercise it; vary these determinants) | status 2026-09-20 |
|---|---|---|---|---|
| PP1 | a policy evaluator can evaluate a plan and sees compliant or non-compliant reasons | `POST /api/planner/proposals` → `GET /api/planner/executions/{id}/evaluation-result` | submit compliant vs fare/cabin/evidence-violating plans; diff verdicts and reasons | WORKS |
| PP2 | a traveller can create, review and submit a draft and sees a queued execution | `/portal/draft/new` → `POST /portal/draft` → `POST /portal/review/{id}/submit` | submit compliant vs violating 58-field drafts; diff policy-lite posture | WORKS |
| PP3 | a traveller can request an exception and an admin can decide it and sees an attributed terminal decision | exception and admin decision routes | create failing-draft exception; reject then retry approve; inspect audit trail | WORKS |
| PP4 | an administrator can escalate an overdue exception and sees it routed to the higher tier | `escalate_draft_exceptions` | create pending exception older than 48h; list/decide and inspect tier | NOT-EXERCISED |
| PP5 | a manager can review a request and decide approve, reject or request changes and sees attributed state | `GET /portal/manager/reviews` → `POST .../{id}/decision` | exercise approve and request_changes; diff state and audit actor | WORKS |
| PP6 | a traveller can correct a requested-change plan and resubmit it and sees the manager's corrected plan | `POST /portal/review/{id}/submit` after `changes_requested` | request changes; correct draft and resubmit; inspect original review | PARTIAL |
| PP7 | an approver can export itinerary or summary and sees usable policy-gated artifacts | `GET /portal/review/{id}/artifacts/{itinerary or summary}` | download both artifacts from compliant and blocked drafts; diff status/content | WORKS |

## Known gaps at draft time
- PP6: there is no route to edit an existing draft; corrected answers create a new draft and leave the manager review on the original (issue #1559 only fixed unchanged resubmission).
