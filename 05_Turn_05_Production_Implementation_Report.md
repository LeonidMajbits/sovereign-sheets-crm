# Turn 05 — Production Implementation Report
## Machine-Native Multi-Tenant Entity & Campaign CRM for Google Sheets

**Implementation release:** 0.5.0rc1 · 23 September 2026  
**Status:** IMPLEMENTATION_CANDIDATE; TARGET_AND_CLOUD_GATES_OPEN  
**Python tests:** 103 passed; compatibility environment SQLite 3.46.1  
**Apps Script checks:** 20 passed in Node with simulated Google interfaces  
**Production runtime requirement:** Python-linked SQLite >=3.51.3; not met by this validation interpreter  
**Baseline ZIP SHA-256:** `65aa15469495bf15eddba505cf0270efe0464aac654a39f69a28a6908a60938e`  
**Report-body SHA-256:** `921d574017b7e70eced4ca28202b8e82ad91ebbfd3339e5bf4c30e2531b16dc1`  
**Receipt scope:** Exact UTF-8 bytes after the standalone delimiter through EOF; complete-file checksum is detached.  
**Destination:** `Deployment Research/Sovereign_Google_Sheets_CRM/`

<!-- RECEIPT-BODY-START -->
## 1. Release decision

**The requested implementation now exists. Release 0.5.0rc1 is an executable implementation candidate, not a production certification.** It contains the local SQLite/FTS engine, authenticated Python CLI, direct Google Sheets publisher and typed scanner, Apps Script ingress, deployment/provisioning tools, and automated integration harnesses. No production CRM, credential, spreadsheet, script deployment or live lab router was modified by this delivery.

The mandatory distinction is between code that was executed in controlled local fixtures and behavior that remains unverified in the intended deployment. The local suite passes. The universal sub-millisecond search claim does not. The currently available linked SQLite is below the frozen runtime floor, and the application refuses that interpreter outside its disposable test instrumentation.

### Baseline custody

The supplied cumulative Turn 4 ZIP was checked at **298,816 bytes**, SHA-256 `65aa15469495bf15eddba505cf0270efe0464aac654a39f69a28a6908a60938e`. The new request's 292,864-byte size does not match those bytes; its hash does. The original ZIP is preserved in private lab custody; baseline conformance documentation is retained under `baseline/`.

The original `schema/crm_schema_v4.sql` is **52,123 bytes**, SHA-256 `3de6e4f720f8b25c9e52d52c7ba94d18759f50e7d03ff0515f2f0126ed3a11dd`. It remains byte-identical. Its 43 ordinary STRICT relations, two FTS5 virtual tables and triggers are not replaced with a smaller incompatible prototype. Runtime metadata and tags are declared separately in an additive extension.

The v4 specification required linked SQLite >=3.51.3. The user's Darwin 3.46.1 compilation result demonstrates declarative compatibility, not satisfaction of that runtime gate. SQLite's documented WAL-reset fix is the reason this implementation keeps the floor rather than weakening it to make a demonstration start. [S1]

## 2. What is delivered

| Requested component | Executable behavior |
|---|---|
| `crm/db.py` | Fresh-only initialization, exclusive local authority ownership, WAL/FULL, per-connection foreign keys and defensive settings, immediate transactions, schema fingerprint, backup/checkpoint and hard runtime gate |
| `crm/entities.py` | All supported typed entity kinds; versioned create/patch/transition/tombstone; immutable aliases/channels and artifact registration; interactions/corrections; guarded claims/chunks; reviewed merge; additive tags |
| `crm/campaigns.py` | Campaign membership and primary selection, sequential stage plans and guarded progression/completion |
| `crm/search.py` | Exact IDs, aliases and qualified channels; literal bounded FTS5; approved tags/organization dependencies; current interaction search; bounded fuzzy candidates and query budget |
| `crm/sync.py` | Durable exact prepared batches, 50 physical-row and 512 KiB bounds, typed literal output, immutable change frames, readback verification, no resend of ambiguous writes, periodic scan slices and strict local dry-run |
| `crm/quarantine.py` | Typed unbased capture, immutable safe metadata with raw bytes only in a private vault, observation lineage, three-way/dependency-aware conflict evidence and explicit adoption/rejection |
| `tools/crm-lab.py` | Thin authenticated Unix-socket client; no direct database access, cloud credential, hidden writer or auto-start daemon |
| `apps_script/Code.gs` | Actual standalone V8 webhook and installed edit/change handlers; signed Drive staging; metadata-only hints; no canonical Sheet writes |
| `tests/test_crm_core.py` | Actual assertions over SQLite state, transactions, FTS, revision history, claims, quarantine, batching, failure injection and the 500-producer fixture |

Supporting modules implement canonical encoding, ULIDs, the accepting engine, exact projections, shared quotas, direct REST authentication, independent Drive custody verification, authenticated broker transport, guarded cloud provisioning and Ed25519 snapshots. The code has no Zapier/Make/Airtable dependency, browser automation, spreadsheet formulas, sidebar or dropdown workflow.

## 3. Local accepting transaction and identity

The existing lab host owns one Database/Engine/Broker. An exclusive local lock prevents another cooperating owner from opening the same authority. Each logical command has a stable operation ID, typed payload, authenticated actor/capabilities, tenant/ledger/epoch and retained base. The CLI cannot select another database path or make a caller-supplied role authoritative.

The engine resolves authenticated exact retries before applying new preconditions. A reused operation ID with changed semantic bytes is rejected. An eligible mutation commits the canonical aggregate, immutable versions, field/relationship stamps, audit chain, approved search state and outbox together. Conflict/no-change outcomes do not fabricate entity revisions. Injected exceptions in the tested acceptance phases roll back all of those effects.

The implementation preserves the important distinctions from planning: a project is not a campaign; a dispatch attempt is not its external conversation; an interaction is not a mutable contact note; harvested output is not accepted work; and a claim token is not an enduring permission after release/recovery.

Claims use an eligibility predicate inside the writer transaction, not blind owner replacement. At most one current holder is accepted in the concurrent fixture. Every worker continuation must present the current generation/holder/epoch. Restart puts held claims into recovery hold. Real executor fencing is a host-supplied verification capability; no time-only takeover or synthetic success is used when that capability is absent.

New IDs use the canonical ULID representation. Durable runtime allocation keeps a local high-water mark; independent IDs are still candidates, not a distributed causal order. The authority commit sequence orders accepted work.

## 4. Retrieval and content boundaries

The two FTS5 indices contain approved current fields only. Stable integer search-document rows map to business ULIDs. Aliases and tags contribute lexical text; neither becomes automatic identity equivalence. Shared domains or email inboxes return multiple candidates. Email normalization preserves the local part and plus-tags. Phone parsing requires the optional maintained parser and fails explicitly when it is missing.

Updates refresh affected search records in the accepting transaction. Historical interactions remain immutable; corrections/retractions remove obsolete current-search results. Organization renames refresh the bounded dependent set. A rename/merge exceeding the admitted fan-out is rejected instead of leaving part of the index stale.

Search compiles bounded literal token-AND grammar and uses canonical joins before returning records. User text does not become arbitrary MATCH syntax, SQL, file paths or tool instructions. BM25 scores are lexical ranking values, not identity probabilities. Fuzzy candidates are capped, truncation is visible, and no result authorizes a merge.

A cooperative **25 ms** request budget now protects ordinary retrieval from an expensive query. On exhaustion, the request returns QUERY_BUDGET and no partial result disguised as complete. This is not an OS hard deadline, a substitute for benchmarking, or a claim that broad queries meet the much smaller release target.

### Measured search fixture

The disposable fixture contains **1,000 mixed entities, 3,000 aliases, 50,000 effective interactions**, and approximately 1,024 bytes per interaction summary. Entities/aliases use public engine commands. Interactions are loaded through 1,000 explicitly internal, audited 50-record fixture transactions; that loading method is not a production ingestion-throughput result.

There are two measured runs, 100 warm-up requests per class/run, 2,000 measured selective/exact/broker requests per run, and 200 measured common-term/fuzzy stress requests per run. The latter falls short of the planning requirement for a full 2,000-query stress repeat, so it cannot certify that requirement. No concurrent writer or cold CLI performance was measured.

| Measured class | Worst p95 of two runs (ms) | Target (ms) | Fixture result |
|---|---:|---:|---|
| Exact ID, warm SQL | 0.0063 | <1 | PASS in this fixture |
| Selective entity FTS + canonical join | 0.0698 | <1 | PASS in this fixture |
| Selective interaction FTS + canonical join | 0.0482 | <1 | PASS in this fixture |
| Common-term entity FTS + canonical join | 1.5556 | <1 | FAIL |
| Common-term interaction FTS + canonical join | 160.6346 | <1 | FAIL |
| Selective full entity retrieval | 0.0879 | <5 | PASS in this fixture |
| Selective full interaction retrieval | 0.0579 | <5 | PASS in this fixture |
| Bounded fuzzy full-name retrieval | 20.4115 | <5 | FAIL |
| Selective full broker entity read (no IPC) | 0.3899 | <5 | PASS in this fixture |

Corrected synthetic fuzzy-quality fixture: target identity in the first 20 results for **200/200** one-character typo queries. Candidate expansion was flagged truncated for **200/200**. This is not a general recall guarantee for natural names or larger corpora.


Raw common-term SQL timings deliberately measure complete ranked retrieval without the ordinary request-budget wrapper. Production calls can instead return QUERY_BUDGET. Timing a rejection is not equivalent to serving a successful ranked result.

Early benchmark files are retained, not erased. The early fuzzy query omitted the trailing word of the stored name; under whole-name edit-distance semantics, that is not a one-character typo and its zero expected-target count was not a valid one-edit recall experiment. The corrected fixture keeps the full stored name and changes exactly one character. The report does not recast that fixture correction as a proven algorithmic recall improvement.

The selected SQL/FTS paths and full broker reads are measured separately. Performance evidence is local Linux/x86-64 compatibility evidence, not a Darwin/ARM64 or supported-SQLite result. Full distributions, errors, candidate truncation and source digests are retained under `verification/`.

## 5. Google Sheets publication and offline safety

The exact v4 headers remain: Directory 31 columns, Active Pipeline 37, Completed Archives 39, `_Control` 20 and `_Changes` 12. Only Directory person/organization `human_status` and `human_note` are editable proposal cells. The publisher never targets or clears them, including after resolution.

Publisher plans use explicit stringValue with TEXT format. Leading `=`, `@`, `+` and `-` in approved output cannot become formulaValue through the API encoder; they are not globally stripped from identity/channel text. Typed formula input, effective-only output and unexpected structured cell content are not imported as literal truth. A local scanner cannot retroactively prevent a formula that Google already executed. [S3]

Publication retains exact resource/generation/ranges/body bytes before dispatch. One atomic request contains the complete bounded audit segment, affected machine-owned cells and receipt/control data. Pipeline/archive moves count two physical rows. Board coalescing can skip intermediate display images, never intermediate accepted audit events.

A private shared quota database coordinates actual consumer-project/principal starts across isolated tenant databases. This is transport bookkeeping, not a second business authority. Production live pacing uses monotonic elapsed time; restart conservatively waits a full quota window. The publisher has one cooldown/backoff owner, no hidden mutation retries and no per-agent Google polling.

The configured internal ceilings remain 30 reads and 20 writes per effective principal/project/minute, with project headroom. They are tighter than Google's documented standard 60-user/300-project read and write budgets. Actual deployment quotas and unrelated traffic still require verification. [S2]

A proved-not-applied response can be retried after shared admission. An ambiguous response becomes UNKNOWN. Complete readback can resolve the narrow single-possibly-applied-send case. A found receipt does not justify resending or continuing when duplicate pending effects remain possible. Unresolved work stays held; local accepted operations remain available while durable capacity allows.

### 500 logical producers: actual observation

The local load test registers **500 synthetic actors**, submits 500 independent person-creation commands using a 32-thread worker pool, and retries all operations unchanged. It verifies one canonical effect per operation and preserved audit/outbox state. Its provider is an in-memory typed-cell boundary, not Google.

The actual encoded payloads drain in **11 batches**, each within 50 physical business rows and 512 KiB. This is not a regression to 500 requests: complete creation/audit/cell framing consumes enough bytes that the theoretical ten-batch row-only minimum is insufficient. The test advances a simulated clock; it does not report live 2.5-minute completion or equate person creation with a small task-field update.

Batch planning was revised after the load test exposed repeated prefix reconstruction. The planner evaluates a bounded candidate once and searches for a fitting prefix when necessary. It does not assert globally optimal packing or discard evidence to reach a desired request count.

## 6. Typed scanning and quarantine

Pull reads bounded verified slots across all three business tabs, checking layout, identity and publisher-owned shadows. Initial empty human inputs create no proposal; observed changes produce lineage, and a later clear can supersede a previously captured proposal. A blank canonical cell is still drift, not a missing proposal. Repeated unchanged observations do not create an echo loop.

Up to 100 new observations are accepted per pass. If a row remains incomplete, the checkpoint retains its replay position. Raw bytes are written with restrictive permissions and fsynced in the non-indexed vault before SQL metadata and cursor advance. If storage fails, no successful capture/repair acknowledgment is invented.

Three-way conflict resolution checks the original verified base, server-owned write/dependency sets and current field/relationship stamps. ABA histories remain conflicts. Unbased Sheet edits never acquire a fabricated original base. The resolver adopts particular captured bytes through a fresh, conditional domain command, preserving both the observation and disposition.

The `proposals resolve` convenience command persists its first intended command/base/identity before acceptance. Retrying it does not silently refresh the base. An explicit reject or keep-local disposition is not a general authorization to execute raw content.

## 7. Apps Script and Drive staging

`apps_script/Code.gs` is executable source, with a deployment manifest and explicit configuration instructions. `doPost` validates a bounded duplicate-aware JSON envelope, its integer-profile JCS/HMAC, sender/audience/tenant, lifetime, payload schema and capabilities. It stages an immutable JSON delivery in the pinned Drive folder and verifies readable content before returning RECEIVED.

The original sender envelope and gateway custody record travel together. The Python consumer independently verifies both, checks actual parent/type/size, retains original operation/base semantics and records file/digest custody with its outcome. A four-hour delay after authenticated intake does not mint a new command or renew a stale business base.

`captureEdit` and `captureChange` are installed trigger handlers. They write metadata-only dirty hints, with no cell value, oldValue, formula, computed output or claimed human role. They never publish canonical state. Missed hints do not eliminate the mandatory scan path. The creator's grant, service limits and real standalone trigger behavior remain deployment conditions. [S4]

Normal handled responses use JSON TextOutput and can return HTTP 200 for an application rejection as well as intake success. The caller must inspect the signed state. Platform errors, HTML, redirects or timeouts are not forced into false success. No browser-login repair path is present.

The bridge is optional. Revoking its creator grant does not grant it fallback publication authority. Script editors and key holders remain trusted administrators; HMAC does not defend against a compromised authorized signer.

## 8. CLI, provisioning and lab integration

The requested commands are implemented, alongside backward-compatible aliases:

- `./lab crm list [--campaign <id>] [--status <state>] [--limit N]`
- `./lab crm ingest <entity.json>`
- `./lab crm get <entity-id-or-alias>` and `show`
- `./lab crm search "<query>"` and `query`, with scope/fuzzy/limit options
- `./lab crm sync [--push | --pull | --dry-run]`
- `./lab crm proposals list`
- `./lab crm proposals resolve <id> --accept` or `--reject`

JSON output and named exit states remain deterministic for the same selected state. Reads stamp their actual snapshot, not a later commit that races with response construction. A partial client send has an UNKNOWN mutation outcome rather than a false assertion that nothing committed. Read-only dry-run performs no Google call, token renewal, quota reservation, evidence write or cursor mutation.

`tools/crm-admin.py` supplies fresh-only provisioning and journaled cloud initialization of an unused bounded spreadsheet. It never overwrites an occupied workbook or assumes edit permission grants creation rights. `tools/crm-host.py` is an explicit reference host for acceptance. It adds no autonomous timer or new manager agent. Existing lab lifecycle integration is supplied in `integration/`; the real Antigravity router was not provided or edited.

`tools/crm-make-command.py` obtains a verified current base from the authenticated broker and writes a new operation packet with exclusive creation. It never ingests the packet and refuses to overwrite it. The actual Unix-socket/CLI test exercises packet preparation, ingest and refusal to regenerate an existing packet.

## 9. Executed evidence and defects found

The final Python suite reports **103 passed, zero failed/errors/skipped**, in **21.041 seconds** in the recorded run. The Node harness reports **20 passed, zero failed**. These include real SQLite WAL files, fault injection, signatures, actual Unix sockets and CLI subprocesses. Google APIs and Apps Script services are simulated boundaries. There is no claim of deployed Google execution.

Useful caught-and-fixed defects include a transport-expiry boundary in the Python/JavaScript path; repeated batch rebuilding; read-response watermarks sampled after the actual read; canonical blanks incorrectly ignored as empty drafts; idle pipeline drift omitted from Directory-only scanning; unnecessary alias-key scans; and quota refill susceptibility to wall-clock jumps. The final tests include regressions for those concrete fixes. Earlier adverse benchmark observations remain visible.

The suite tests atomic rejection/no-change/idempotency, stale bases and claims, immutable historical rows, typed formula isolation, effective interactions and merged identities, orphan-free FK state, raw-vault write failures, exact prepared publication/readback, uncertain-write holds, source-directory refusal, signed snapshots, schema fingerprint mismatch and local RPC behavior. These are targeted tests, not an assertion that every possible predicate combination was exhausted.

The original **109 planning obligations** remain unchanged as a baseline. `verification/acceptance_status_v5.json` maps evidence categories without marking target/runtime/cloud oracles passed merely because related mocks passed.

## 10. Open gates that must not be hidden

**Runtime:** linked >=3.51.3 and actual Darwin storage/crash behavior have not been exercised here. Disposable tests explicitly lower the floor to available 3.46.1. There is no production bypass environment variable or CLI flag.

**Latency:** the blanket sub-millisecond claim fails in common-term ranked classes. Optional fuzzy quality/latency is separately reported. Concurrent-writer, cold CLI and complete stress repetition remain open.

**Cloud:** no live credentials or resources were deployed. IAM, unattended token renewal, actual quotas, typed readback, triggers and grant-loss behavior need real disposable-resource evidence.

**Recovery:** automatic different-workbook allocation/cutover is not implemented. Same-resource uncertain reconciliation exists; an unresolved case stays in a durable hold. Existing-database migration is also not implemented and never occurs implicitly.

**Executor fencing:** the host must supply a real proof callback. Snapshot restore remains RECOVERY_HOLD; it is not a second authority or automatic promotion. Real remote side effects are outside the CRM's transactional scope.

**Confidentiality/maintenance:** signed local snapshots are plaintext with restrictive permissions, not encrypted backups. No raw-evidence snapshot is automatically uploaded. Staging retirement, long-term quota-ledger compaction and automated resource compaction remain administrative maintenance work. Capacity is finite and acknowledged history is never silently discarded.

**Optional features:** phone metadata was not installed in this validation environment; telemetry remains disabled without its actual producer contract. The optional human table-output formatter is not included. These omissions return explicit behavior instead of silently pretending the feature is available.

The precise status is **IMPLEMENTATION_CANDIDATE / TARGET_AND_CLOUD_GATES_OPEN**. `docs/CONFORMANCE.md` records the bounded amendments and gaps. This is a useful runnable code delivery, but not grounds to waive the project's own final release tests.

## 11. Integrity and handoff

The archive contains all required source modules, schemas, tools, tests, documentation, machine-readable results, original baseline ZIP and a sorted SHA-256 manifest. No database, WAL/SHM, real customer data, service-account key, local RPC secret or vendored dependency is distributed.

The header body digest covers bytes following the standalone receipt delimiter through EOF. The detached document receipt covers the complete Markdown. `MANIFEST.sha256` covers every other archive member and excludes itself; the ZIP checksum is detached. The post-upload delivery receipt is separate to avoid circular hashes. Upload verification attests artifact bytes, not deployed CRM correctness.

### Primary-source references

[S1] SQLite WAL: https://sqlite.org/wal.html — documented storage premises and WAL-reset fix.

[S2] Google Sheets limits: https://developers.google.com/workspace/sheets/api/limits — provider read/write budgets; no measured throughput claim.

[S3] Google CellData: https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/cells — typed source/effective-value distinction.

[S4] Apps Script installable triggers: https://developers.google.com/apps-script/guides/triggers/installable — creator-authorized standalone trigger behavior.

Further maintainer references and unchanged planning contracts are retained in `docs/PRIMARY_SOURCES.md` and the original cumulative baseline.
