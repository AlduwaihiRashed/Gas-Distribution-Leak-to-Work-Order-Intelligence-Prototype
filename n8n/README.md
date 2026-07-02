# N8N Workflows — Node Reference

Two workflows, both calling `src/api.py` (port 8000) at `host.containers.internal` (podman's DNS name for the host). Import via n8n UI (Workflows → Import from File) or push via the REST API.

**Grade-1 physical isolation (blueprint D7/R8) is not in either workflow, on purpose.** It fires synchronously inside `live_ingest.py` at grading time, over MQTT, before N8N's poll cycle would ever see the incident — see `CLAUDE.md`'s "bypasses N8N's polling cadence" note and `docs/hardware-implementation-guide.md`. These workflows only handle work-order creation/routing and the (unrelated, still human-gated) dispatch approval — the actuator state shows up as a read-only field on the work-order payloads they move around, not as something either workflow triggers.

## Workflow A — `L2WO - Auto Work Order Routing`

No manual trigger — this is the "detect + action" loop (blueprint R5).

| Node | Gets | Does | Outputs |
|---|---|---|---|
| **Poll every 10s** | nothing (schedule) | fires on a timer | empty item, every 10s |
| **GET pending incidents** | trigger tick | `GET /incidents/pending` — graded incidents not yet in the queue | success → array of `{incident_id, segment_id, grade}` (n8n auto-splits the array into one item per incident) · error → routes to *error output* (branch 2) |
| **Synthesize + auto-route (M7)** | one incident item | `POST /work-orders/synthesize {incident_id}` — the API claims it (`IN_PROGRESS`), calls the LLM (or falls back internally to a degraded template if Ollama fails), writes it into `queue.json` with status `AWAITING_APPROVAL` | success → full work-order object (branch 1) · error → *error output* (branch 2), only fires if the API/network itself is unreachable (an Ollama-only failure already comes back as a normal 200 with `degraded_mode: true`) |
| **Routed to dashboard queue** | successful work order | no-op — the API already wrote it, this is just the terminal node for the happy path | — |
| **Build per-incident fallback alert** | the failed item (still has `incident_id`/`segment_id`/`grade` from the earlier GET, since the item survives error routing) | builds a JSON banner line, base64-encodes it as binary (required by the file-write node) | one item with `binary.data` |
| **Build pipeline-outage alert** | the failed GET-pending item (no incident data available — the outage happened before we even knew what was pending) | builds a generic "pipeline stalled" banner | one item with `binary.data` |
| **Write alert log (latest state)** | either alert branch | overwrites `/home/node/.n8n-files/l2wo_orchestration_alerts.log` with the latest banner (n8n's own append mode has a bug — always opens with an invalid flag — so this uses overwrite; the file always reflects current state, not full history) | file on disk inside the n8n container |

**Why two separate error branches:** if only the synthesize call is wired for `continueErrorOutput`, a *total* API outage kills the whole execution at the earlier GET step before ever reaching the fallback — nothing gets logged. Both HTTP nodes need their own error branch.

## Workflow B — `L2WO - Dispatch Approval Gate`

The one human gate in the system. Never touches creation/routing — only authorizes physical dispatch.

| Node | Gets | Does | Outputs |
|---|---|---|---|
| **Approval webhook** | `POST /webhook/approve-dispatch {incident_id}` from the dashboard's "Approve" button | receives the request | `$json.body.incident_id` |
| **Approve physical dispatch (human gate)** | incident_id | `POST /work-orders/{id}/approve` — flips status `AWAITING_APPROVAL → APPROVED_DISPATCHED`; 409 if already approved/dispatched or not found | success → updated work order (branch 1) · error → error detail (branch 2) |
| **Respond: dispatched** | approved work order | 200 JSON response back to caller | HTTP response |
| **Respond: approval failed** | error detail | 502 JSON response with the underlying error message (e.g. the 409) | HTTP response |

## Scenarios

- **Happy path:** poll → GET pending (has items) → synthesize (200, `degraded_mode: false`) → routed. Repeats every 10s until `/incidents/pending` is empty.
- **Ollama down/times out:** synthesize call still returns 200 (the API's own `degraded_work_order()` fallback fires internally) — n8n sees a normal success, never touches its own error branch. Work order is banner-flagged `DEGRADED MODE` in the queue itself.
- **Whole API/network down:** GET pending fails → *Build pipeline-outage alert* → alert log shows "pipeline stalled." Once the API comes back, the very next 10s poll resumes automatically — no restart needed.
- **API dies mid-synthesis for one incident:** GET pending succeeded (had the incident's id/segment/grade), synthesize call fails → *Build per-incident fallback alert* → alert log shows that specific incident with a `DEGRADED MODE` banner.
- **Double approve:** second `/approve` call gets a 409 from the API → n8n's error branch → dashboard gets a 502 with the conflict message, not a false "success."
- **Two n8n executions overlap on the same incident:** can't duplicate-call Ollama — the API claims the incident (`IN_PROGRESS`) synchronously before the slow LLM call, so the second execution's GET pending won't even see it as pending anymore.
