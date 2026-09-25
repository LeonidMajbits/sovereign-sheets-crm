# Runtime conformance and admission — 0.5.0rc1

## Release classification

This is an executable implementation candidate, not another planning package and not a certified live deployment. The six requested package modules, real authenticated CLI, direct REST publisher/scanner, standalone Apps Script, and automated tests are present. There is no placeholder implementation that silently claims success for an unavailable provider or recovery capability.

The unchanged Turn 4 ZIP and its frozen schemas/contracts remain evidence. The implementation does not retroactively mark its 109 cumulative acceptance obligations passed. Executed tests are individually named in `verification/pytest-results.xml` and `verification/apps_script_node_results.json`. They establish the behaviors their fixtures exercise, not all production premises.

## Baseline retained

The 52,123-byte `schema/crm_schema_v4.sql` has the original SHA-256. All 43 ordinary tables and two FTS5 virtual tables remain. The exact five-tab header manifest is unchanged. Entity identity is ULID; command order is the home commit sequence. Cloud publication is a projection, never a second commit authority. Raw edits are unbased observations and accepted claims are conditional, generation-fenced transitions.

All 19 v4 command alternatives have handlers. The registry, typed JSON validation, authentic retained-base checks, actor capabilities and current business predicates gate them. Handler presence does not imply exhaustive integration coverage of every possible parent/relationship case.

The runtime excludes network I/O from accepting write transactions. Canonical state, history, approved search documents and publication obligation commit together. Evidence objects are durable before their SQL references. Transport acknowledgment bookkeeping does not recursively create business publication obligations.

## Explicit implementation amendments

| Topic | Implemented choice |
|---|---|
| New request for searchable tags | Add versioned `entity.tag.set` under `crm.command.v5`, with its own typed schema; v4 alternatives remain unchanged. Tags contribute lexical text, not person-name equivalence. |
| Runtime metadata absent from the declarative schema | Five additive tables in `runtime_extension_v5.sql`: runtime_state, entity_tags, projection_slots, projection_shadows, local_nonces. The last is reserved; local RPC nonce admission currently uses a bounded in-memory window, while business deduplication is durable. |
| Shared quotas across tenant-isolated ledgers | One private operational `quota.db` shared by the effective consumer-project/principal. It owns durable physical-start admission, not business truth. All brokers sharing that quota must share the configured quota root. The frozen per-ledger quota table is retained, not falsely populated as the shared authority. |
| Live quota clock | Production pacing derives elapsed time from a monotonic clock. Restarts impose a conservative 60-second hold over persisted reservations. Deterministic injected clocks exist only for tests. |
| Quota backoff | One shared deterministic capped backoff/cooldown owner, with five-minute hold after eight rejections. No per-agent loops. The earlier proposed randomized jitter is not implemented; no jitter-based claim is made. |
| Invocation compatibility | `get` aliases `show`; `search` aliases `query`. New `proposals list/resolve` is a typed convenience over observation.resolve, not a force-overwrite path. JSON remains the sole CLI output format; the prior optional table renderer is not included. |
| Destructive/complex operations | Some operations conservatively require the current ledger base instead of accepting every theoretically independent stale base. This can cause more conflicts, never an unguarded overwrite. |
| Fan-out admission | At most 25 refreshed entities in one command, permitting a conservative upper bound of 50 physical terminal-move rows. Search/relationship refresh limits can reject larger renames/merges. No hidden partial operation or oversized snapshot escape hatch. |
| JSON canonicalization | Tested RFC8785-compatible integer-only profile. Fractions/non-finite values are rejected; large counters remain decimal strings. General floating-point JCS is not claimed. |
| Retrieval overload | Cooperative 25 ms query budget; expensive requests return QUERY_BUDGET without a partial answer. This is a service safety boundary, not a 1 ms guarantee or a hard OS deadline. |
| Capture scheduling | A bounded pass scans verified slots across all three business tabs, not only Directory. Human proposals are only Directory person/organization fields. At most 100 new observations are committed per pass; checkpoints replay the uncompleted row safely. |
| Bootstrap | A separate administrative provisioner accepts only an unused, bounded, single-grid spreadsheet, journals its exact request, and verifies the resulting layout before activation. It never obtains creation rights from an assumption or modifies an occupied workbook. |
| Existing lab integration | A host embedding API and router snippet are supplied. The user's actual Antigravity router/repository was not available for editing, so the included `lab` is an acceptance shim, not a claim that the real router has been patched. |

## Security and trust boundaries

`safe_cell` uses explicit stringValue/TEXT. It does not strip `=`, `@`, `+` or `-` from a legitimate accepted string; those bytes are inert at the API output boundary. Native formula input is rejected by its typed origin. Conservative raw-input leading-token checks additionally stage suspicious drafts; evaluated results never become trusted literal data. Context-specific channel parsing retains legitimate international phone plus signs. CSV export is not provided.

Rejected raw evidence is opaque content-addressed storage outside the database text columns, source tree, synchronized folders and normal search roots. SQL and cloud audit receive only bounded metadata/digests. No default quarantine preview, summarizer, URL fetcher or model ingestion exists. Text that passes literal validation still does not grant a capability.

Per-principal local RPC keys map to configured actors/capabilities. Authentication happens before outcome disclosure. A saved operator key is not a recommended credential for every subagent. Same-OS-user arbitrary shell access is outside the isolation supplied by Unix permissions; use real process/account isolation for hostile agents. HMAC is shared-secret authentication, not nonrepudiation against another key holder.

Apps Script remains optional ingress only. Trigger files contain metadata, never raw cell values/formulas. Command deliveries retain the original sender MAC and a gateway custody MAC; the home verifies both and applies the original business base. An intake response does not mean a domain commit. No code tries to restore a revoked grant by opening a browser.

## Remaining production gates and missing extensions

1. **Supported linked SQLite and target OS:** this environment links 3.46.1. Normal execution requires >=3.51.3 and refuses the old version before creating runtime files. The tests lower the gate only inside fresh disposable compatibility fixtures. Darwin ARM64, the required linked build, fsync/power-loss and real crash/restart behavior still require target execution.
2. **Search service level:** selective measured requests may pass, while common-term ranked searches and fuzzy cases have separate failure results. A universal sub-millisecond claim is not released. Concurrent-writer, cold CLI and full stress-repeat gates remain open.
3. **Live Google:** no service-account credential, workbook, Apps Script project/deployment or installed trigger was supplied/deployed. REST and script logic were exercised through simulated provider boundaries. Real scopes, grants, quota attribution, redirects, typed scans and publication readback remain deployment tests.
4. **Unknown-resource rotation:** same-resource readback reconciliation is implemented. Automatic allocation/cutover to a different spare spreadsheet is not. Unresolved uncertainty remains a durable hold; no doubtful resource is reused automatically.
5. **Executor recovery:** claim recovery requires the host's real fencing-verification callback and no unsettled external action. The default has no such verifier and returns FENCING_PROVIDER_REQUIRED. This package does not execute remote models, send messages or cancel external side effects.
6. **Existing database migration:** fresh initialization only. Existing, independently created databases are neither renamed nor overwritten. Reviewed migrations and schema evolution remain separate work.
7. **Restore promotion:** signed full local snapshots and a verified restore into RECOVERY_HOLD are implemented. Automatic promotion, old-home fencing and continuation certification are not. A snapshot is not permission to run a second home.
8. **Backup confidentiality:** snapshots contain plaintext database/evidence bytes with restrictive permissions. They are not encrypted archives. Use authorized encrypted storage before cloud transport; no automatic raw-evidence cloud backup is supplied.
9. **Maintenance/retention:** archive and staging retirement, long-term quota-ledger compaction and automatic resource compaction are not scheduled. Capacity guards stop new unsafe admission. Operators must size and provision storage; already accepted history is not discarded.
10. **Optional capabilities:** international phone metadata requires the separately installed maintained parser; it was unavailable in this environment. Telemetry is disabled pending a real producer contract. No undocumented fallback normalizer or fabricated Ashby meanings are used.

## What constitutes release admission

Repeat the actual suite on the supported interpreter and target filesystem. Inspect process and key isolation. Provision a disposable workbook and execute real bootstrap/publish/readback/edit-capture/ingress tests. Exercise the actual lab executor fence. Run the fixed search fixture under the required concurrency, record failures as failures, and choose whether to narrow or improve the promised latency class. Obtain a reviewed recovery/maintenance plan before relying on unattended long-lived operation.

Until those conditions are met, the release status is IMPLEMENTATION_CANDIDATE / TARGET_AND_CLOUD_GATES_OPEN, not PRODUCTION_CERTIFIED.
