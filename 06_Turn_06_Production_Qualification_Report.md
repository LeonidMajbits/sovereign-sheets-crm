# Turn 06 — Production Qualification Report
## Sovereign Google Sheets CRM · v1.0.0 qualification release

**Date:** 24 September 2026  
**Status:** CONDITIONAL_TARGET_AND_CLOUD_GATES_OPEN; production_admitted=false  
**Primary fixture:** 100 workers · 10 isolated tenants · 50,000 mutations · 50,000 exact retries  
**Actual execution:** Linux x86-64 · Python 3.13.5 · SQLite 3.46.1 · Google boundary simulated  
**Required production runtime:** Python-linked SQLite >=3.51.3; Darwin target and live cloud gates remain open  
**Body SHA-256:** `42b58c52a9a7d0a25e295007143a990bf5778d8a06b4ef36dc778e714b77d3bf`  
**Hash scope:** UTF-8 bytes immediately after the standalone receipt delimiter and LF, through EOF. Complete-file checksum is detached.  
**Destination:** Deployment Research/Sovereign_Google_Sheets_CRM/

<!-- RECEIPT-BODY-START -->
## 1. Release disposition

**The requested 100-worker / 50,000-operation matrix passed its executed local and simulated-provider oracles. Production admission remains false.** This release contains the implementation, qualification runners, machine-readable observations, exact command trace, failure injection logs and target-machine instructions. The version `1.0.0` and requested archive name identify this delivered code/evidence package; they do not certify an unexecuted ZION or live-Google deployment.

The local ledger is the transactional authority, not a disposable shadow cache. The user reports that previous turns landed in the lab. This turn independently checks the delivered source and the executions documented here, not unseen runs on that lab machine. The inherited Turn 5 runtime/cloud/search gates are not waived by the new release number. [B5 §§1,10]

| Qualification layer | Observed disposition |
|---|---|
| 100 workers, 10 tenant ledgers, 50,000 primary mutations and 50,000 exact retries | PASS on the stated Linux compatibility host |
| Complete retained operation/revision/history and simulated cloud-frame comparisons | PASS |
| 100-worker concurrent ingest/publication supplementary workload | PASS, 2,000 mutations |
| Lamport contention, conditional claims, five abrupt process exits | PASS within the stated fixtures |
| Python / Node regression suites | 134 / 20 passed |
| ZION M3 Max / Darwin ARM64 execution | NOT RUN here |
| Required Python-linked SQLite >=3.51.3 | NOT MET by this interpreter |
| Live Google permissions, token renewal, provider quota, Apps Script deployment | NOT RUN |
| Universal sub-millisecond search and complete recovery admission | Not released; prior failures/gaps remain |

`qualification/release_status.json` is the machine-readable disposition. A file transfer checksum is evidence of delivered bytes, not evidence of deployed correctness.

## 2. Baseline custody and controlled changes

The original Turn 5 code archive was checked at **493,873 bytes**, SHA-256 `1570fd3e1fe2b7b729b4fdf9667c70e044e4dc1ebc8f606f2b851a3bee909137`. All 81 of its manifest entries verified. Its exact bytes and the previous Turn 4 cumulative archive are preserved in private lab custody; baseline conformance documentation is retained under `baseline/`.

The **52,123-byte v4 DDL remains unchanged**, SHA-256 `3de6e4f720f8b25c9e52d52c7ba94d18759f50e7d03ff0515f2f0126ed3a11dd`. No replacement prototype database or alternate transaction engine was substituted. This turn operates through the existing `Engine.ingest`, actual SQLite storage, existing publisher and original fixed Sheets headers.

Runtime changes are deliberately bounded: an opt-in v6 prose-register command; genuine injectable full jitter in shared quota scheduling; a byte-equivalent canonical encoder optimization; the command preparer's v6 schema selection; and version/qualification metadata. `qualification/core_changes.patch` and `qualification/evidence/core_changes.json` identify the differences. The original source archive remains the before-image.

The full matrix snapshots its tested runtime/schema/runner digests in `qualification/evidence/full/environment.json`. The report-generation and supplementary-oracle files added afterward do not retroactively become part of that earlier source snapshot. Core runtime modules were not edited during the full run. The final archive manifest covers all delivered files.

## 3. Actual host, runtime and execution boundary

The observed execution environment is **Linux x86-64**, Python **3.13.5**, linked SQLite **3.46.1**, and Node **v22.16.0**. The container reports an Intel Xeon Platinum 8573C host CPU, five visible logical CPUs, a four-CPU cgroup allowance and 4 GiB memory limit. These are container observations, not bare-metal M3 specifications. Full recorded details are in `qualification/evidence/runtime_probe.json`.

Fresh fixtures use real on-disk SQLite files, `journal_mode=WAL`, `synchronous=FULL` (numeric 2), foreign keys, actual Python threads and actual local locks. A published library's semantics do not prove the host's physical disk or power-failure behavior. SQLite documents both the one-writer WAL model and the reset-race fix included in 3.51.3 and later. The frozen runtime minimum remains in force. [S1]

The explicit **compatibility-only qualification option** temporarily lowers the library floor only for newly generated temporary fixtures and restores the original setting afterward. It does not open or migrate an existing CRM root. There is no normal runtime environment variable or CLI flag that disables the production requirement. Attempts to obtain a newer official library in this environment failed; no upgraded binary was used or bundled.

The full matrix uses a deterministic typed Google boundary, not live Sheets. The quota clock is virtual. Real measured CPU/wall durations are kept distinct from the virtual four-hour partition and scheduled publication intervals. Supplemental tests overlapped portions of the drain on the same container, so wall durations are not isolated hardware throughput certification.

## 4. Primary multi-tenant workload

The full workload is intentionally exact:

| Quantity | Executed fixture |
|---|---:|
| Concurrent Python worker threads | 100 |
| Peak overlapping calls into the accepting engine | 76 |
| Independently isolated tenant ledgers | 10 |
| Primary typed command admissions | 50,000 |
| Entity/campaign creations | 10,000 |
| Subsequent Lamport note mutations | 40,000 |
| Exact original-packet retries | 50,000 |
| Distinct current entity/campaign rows | 10,000 |
| Person rows / campaign rows | 9,000 / 1,000 |
| Primary admissions per worker | 500 |

Each worker creates 100 records, then submits four updates per record, for five canonical revisions per record. Those updates are real public-engine commands, not direct SQL bulk inserts. Actor registration is explicit fixture setup and is excluded from the 50,000 count. Operations, payloads, outcomes and per-call measurements are retained in `operation_trace.jsonl.gz`.

The workload is **50,000 upsert-like mutations over 10,000 current records**, not 50,000 distinct records. Generic SQL UPSERT is not used to bypass the frozen typed-ingest contract. Ten workers share each tenant ledger and its tab set. Deliberately overlapping entity IDs across different tenants exercise namespace boundaries. A packet bound to another tenant/ledger is rejected by the real engine.

Untrusted tenants retain separate database files and workbooks. “Shared tabs” means workers inside a tenant share Directory / Active Pipeline / Completed Archives, not that one workbook somehow hides one tenant from another authorized reader. This keeps the previous disclosure contract intact. [B4 §0.2]

The primary path is the **trusted embedded engine**. It is not 50,000 authenticated Unix-socket calls and not 100 LLM inference processes. The separate socket experiment below measures that boundary without conflating it with internal engine throughput.

### Admission and replay measurements

| Measured class | Samples | p50 / p95 / p99 / max (ms) |
|---|---:|---|
| Accepting-engine calls, including contention | 50,000 | 347.102 / 873.716 / 1,265.824 / 3,514.390 |
| Exact retry lookup/return | 50,000 | 125.494 / 262.267 / 347.022 / 698.175 |

Admission **plus all exact retries** took **432.678 real seconds**. This measurement includes both phases; it is not misreported as fresh-admission-only throughput. Percentiles use the nearest-rank observation over recorded calls. There is one full-scale run, not a multi-run statistical qualification of every possible scheduling order.

### Integrity oracles

Every primary command has exactly one retained operation outcome and audit transaction. All 50,000 entity revisions exist. Every current row reaches revision 5 with its expected selected note. Foreign-key and database integrity checks pass for each ledger, and all ten complete audit chains validate. Replaying the original 50,000 packets adds no canonical effects or new operation outcomes.

The independent trace oracle reconstructs **40,000 Lamport decisions**, all receive-clock updates and **10,000 final registers** without importing the Lamport implementation. A separate read-only storage oracle verifies **10,000 exact current FTS documents**, matching accepted note text and source revisions—not merely matching row counts. Their result files are `register_trace_oracle.json` and `exact_storage_oracle.json`.

Observed violations in this fixture: **0 lost admitted operations, 0 missing versions, 0 duplicate canonical effects, 0 cross-tenant accepts.** Those are exhaustive checks over this finite trace, not a claim that finite testing proves absence under every deployment/failure pattern.

## 5. Explicit Lamport LWW amendment

The new request asks for LWW, whereas the previous architecture intentionally rejected arbitrary last-writer conflict overrides. The release therefore adds a separately versioned, separately authorized command rather than silently weakening the old commands.

`entity.lww.set` uses `crm.command.v6` and requires **`entity.lww`** capability. The permitted registers are `note` and `next_action` on live person, organization, campaign and project entities. First use requires a valid retained base with an unchanged field and claims that field's policy. An ordinary based patch or raw-human-note adoption cannot subsequently bypass that register ownership. Unsupported ownership reset/migration is not invented.

For candidate x, define:

**rank(x) = (integer logical_clock, authenticated actor_id, operation_id)**

The current register head is the maximum rank. The receiving broker's logical clock advances as **C' = max(C, incoming_clock) + 1**. Actor identity comes from authenticated context, never a value inside the proposed note. Counters use checked signed-64-bit bounds, not floating-point wall-clock seconds. Lamport's original work supplies the logical-ordering framework; the exact register scope, tie-break and admission rules here are this implementation's explicit choices. [S3]

For a fixed set of valid candidates after ownership is established, max under this total order is associative, commutative and idempotent. That gives an order-independent selected head. It does not make every history identical: accepted revision count and audit order can differ with delivery order. It also does not establish original human intent or true chronology. Senders must maintain a legitimate logical clock; an authorized maliciously inflated clock can dominate a register, so capability custody remains important.

All candidates, including losing candidates, generate immutable `lamport.candidate` audit events. A losing candidate or same-value winner does not invent an entity revision. A same-value winner may still advance the rank head. The head, receiving clock, outcome, audit, current field changes, approved search updates and outbox commit atomically.

Four additional **100-way same-register contests** used different seeded launch orders. Each retained 100 candidates, returned the same deterministic maximum-rank winner, and accepted exact retries without additional effects. Actual committed orders are recorded. Final canonical revision counts varied (10, 9, 9, 5), which is expected: different numbers of intermediate candidates temporarily outranked the head.

**Excluded:** status transitions, identities, claim holders/generations, money, contract terms and acceptance evidence. Those retain based dependencies and current-state predicates. Raw Sheet cells remain unbased observations. The optional Apps Script bridge has not been upgraded to accept v6; it rejects unknown alternatives. The new path is local broker/CLI only. See `docs/LAMPORT_EXTENSION.md` and the exact JSON schema.

### What zero overwrite can mean

LWW necessarily replaces a selected current value. Two conflicting values cannot both remain the current value of one scalar cell. The qualified no-loss claim means **every admitted candidate remains in immutable evidence, no unrelated field is changed, and publication never overwrites human-owned draft cells**. It does not mean a winning update leaves the old value current.

Likewise, a scalar LWW balance is not a safe spending algorithm. The retained negative control starts at 100 and applies two independently authorized-looking debits of 80; LWW can display 20 while 160 has been spent. The example is an algebraic counterexample, not a payment test. This CRM does not settle financial transactions.

## 6. Exclusive claims and abrupt exits

Ten separate rounds launched **100 competing acquisitions** against one eligible dispatch resource. Each round produced **one current holder and 99 conflicts**. All 100 exact retries per round added zero audit transactions. After authorized release and new acquisition, the old holder's release was rejected under its stale token. Submission spread ranged from 52.012 to 65.838 ms; no unmeasured 10-ms completion guarantee is claimed.

These results exercise the existing predicate inside the serialized write transaction. A transaction keyword alone would not prevent blind owner replacement. The result qualifies **exclusive CRM claims and one canonical effect per stable operation**, not exactly-once remote model execution or financial double-spend prevention. Real executor fencing remains a host integration requirement. [B3 §4]

Five additional cases used actual abruptly exiting child processes, not only a caught Python exception:

| Exit point | Exit code | Revision visible after reopen, before retry | Revision after exact retry |
|---|---:|---:|---:|
| after_domain | 73 | 1 | 2 |
| after_search | 73 | 1 | 2 |
| before_outbox | 73 | 1 | 2 |
| before_commit | 73 | 1 | 2 |
| after_commit | 74 | 2 | 2 |

Pre-commit cases retain the original revision and commit once when the original command is retried. The post-commit case retains its committed revision and returns that original outcome on retry. Every case finishes with a valid audit chain. These are Linux process-exit/WAL reopen tests, not destructive power cuts or APFS durability tests.

## 7. Quota and four-hour partition resilience

Google publishes separate Sheets read/write quotas of 60 per user/project per minute and 300 per project per minute, with requests batchable. This implementation deliberately uses tighter shared internal ceilings and actual physical-call reservations. Provider configuration and other traffic can still differ in a real deployment. [S2]

This turn found that the previous rejection scheduler used deterministic exponential delays. It now uses genuine injectable **full jitter**, with production randomness and seeded tests. The first seven failures use a bounded exponential scale; eight failures enter a shared minimum five-minute probe interval. Retry-After, 15-second write pacing, rolling quotas, persistent cooldowns and UNKNOWN safety rules remain lower bounds. A malformed jitter source rolls back its state update.

The primary resilience fixture first forms the complete local backlog with no cloud calls, closes and reopens all ten real tenant databases, activates the simulated provider, makes it offline and verifies that **50,000 obligations remain pending**. It then advances a **14,400-second virtual partition**, restores connectivity and restarts the shared quota scheduler. A restart cannot obtain a fresh free quota burst.

Recovery injects eight initial pre-application quota rejections plus periodic further 429s. Two selected writes apply successfully but lose their response. The actual publisher keeps its exact prepared identity, reads complete evidence and resolves the narrow single-possibly-applied-send case without repeating the applied mutation. Other unresolved ambiguity still holds; the harness does not silently turn UNKNOWN into a safe fresh send.

| Publication metric | Observed |
|---|---:|
| Verified encoded batches | 1,230 |
| Physical write attempts | 1,250 |
| Injected confirmed-not-applied 429 responses | 20 |
| Applied writes with deliberately lost responses | 2 |
| Shared quota deferrals | 2,021 |
| Largest complete request | 524,261 bytes |
| Largest physical business-row batch | 48 |
| Complete encoded publication bytes | 633,561,969 |
| Maximum starts in any modeled rolling minute, reads / writes | 30 / 4 |
| Remaining publication obligations | 0 |
| Modeled post-reconnection duration | 19,129.799 seconds |
| Real wall time spent computing/applying/verifying simulated drain | 1,371.374 seconds |

The four-hour partition is **virtual**, not four hours spent disconnected in this session. The backlog was populated before the outage/recovery phase; the primary test does not pretend it continuously mixed all admissions and cloud writes. The supplementary streaming case below addresses that distinct interleaving.

The complete original JCS bytes for all 50,000 transaction manifests and 140,000 audit events are also retained in compressed `audit_trace.jsonl.gz`, not merely summarized as green counts. `qualification/audit_evidence.py` independently re-verifies every digest, previous-head link, event ordinal/count and operation identity without importing the CRM engine. Its checked result is retained separately.

All batches obey **50 physical business rows and 524,288 complete bytes**. Audit frames consume bytes even where current board rows are coalesced. The final independent provider oracle compares **50,000 transaction manifests and 140,000 exact event bodies/digests** with the local ledger, then checks all 10,000 business rows. Every outbox obligation is VERIFIED. No per-agent Google loop or manual browser repair was introduced.

The fake provider validates request shape, typed literal writes, generation/row addressing and human-column exclusion before atomic application. It rejects modifications to already occupied immutable change cells. It does not simulate Google's entire distributed implementation, IAM, OAuth behavior, actual remote latency, billing, outages or undocumented service behavior.

## 8. Concurrent publication while workers are still writing

A separate streaming workload runs **100 workers against one shared tenant ledger/workbook**, admitting **2,000 mutations over 400 records**, while a publisher thread concurrently drains accepted changes. Peak overlapping accepting-engine calls was **70**.

**5 publication observations occurred before all mutations were admitted.** Their batch numbers and exact admitted counts are retained, establishing actual overlap rather than simply naming a test “streaming.” Final drain used **50 batches / 52 attempts**, left zero pending work, and preserved all **2,000 manifests / 5,600 events** exactly. Two initial simulated quota rejections were present.

Its real wall duration was **65.641 seconds**. Accepting-call p50/p95/p99/max was **198.165 / 822.920 / 1,112.659 / 2,873.903 ms**. This supplementary workload is not silently added to the primary 50,000 count and is not an independent live-Google measurement. It specifically exercises future accepted updates arriving while older projection after-images and receipts are being published.

## 9. Authenticated local transport, with backpressure exposed

The supplementary RPC test used **100 actual Unix-socket clients**, **500 original mutations** and **500 exact retries** through the unchanged authenticated broker. The server retains its 32-in-flight bound. It is not 100 unlimited simultaneous handlers.

All logical operations and exact retries completed, with exactly 500 entity versions/outcomes and a valid audit chain. There were **2,622 wire attempts**: **1,312 LOCAL_OUTCOME_UNKNOWN** and **310 BROKER_RESPONSE** transient outcomes required bounded client retry. The clients retained the same semantic packets and operation IDs. No retry minted a replacement identity or refreshed a stale base.

Logical-request latency including retries was **210.594 / 2,143.536 / 4,232.900 / 6,435.353 ms**, with **6.816 seconds** wall duration for the complete fixture. These are not sub-millisecond end-to-end calls. The nonce cache still has a 4,096-entry/120-second admission window; this bounded 1,000-logical-request test is not a 50,000-fresh-RPC soak. The internal-engine throughput cannot be extrapolated to that sustained external-client rate.

## 10. Regression results, evidence quality and carried-forward limits

The final Python run reports **134 passed, zero failures/errors/skips**, in **28.569 seconds** in its JUnit record. The final standalone Node run reports **20 passed and 0 failed**, executing the actual Apps Script source against mocked services. One earlier JUnit-format warning is retained in its historical log; the final run uses compatible xunit1 metadata. Earlier capability-registration test failures during construction were corrected and the adverse log is retained rather than rewritten as a pass.

New regression coverage includes LWW loser history, exact rank tie-breaking, authenticated actors, first-use stale-base rejection, forbidden fields/clocks, separate capability checks, atomic clock/head rollback, tombstone protection, same-value winners, null values, field ownership, schema consistency, real socket command preparation, jitter bounds/Retry-After and persistent holds. A **1,000-tree** multilingual/nested comparison establishes exact canonical-byte equivalence to the prior encoder for those samples; the original cross-language crypto tests also remain green.

The actual full-matrix source files are hashed before execution; no core runtime source changed while it ran. Separate test/oracle additions have their own final manifest entries. Syntax compilation and shell syntax checks were also performed. No test binary or success badge replaces the raw trace.

**Search:** this turn verifies exact approved current indexing and does not claim a new successful universal latency measurement. The previous common-term entity FTS, common-term interaction FTS and fuzzy p95 failures remain carried forward: **1.5556 ms, 160.6346 ms and 20.4115 ms**, respectively, on the old fixed fixture. FTS5 supplies lexical machinery, not a system latency warranty. [B5 §4; S4] The target runner repeats the full search fixture with 2,000 observations per class/run. A budget rejection is not a successful fast result.

**Recovery and security:** automatic different-workbook allocation/cutover, migration of an unrelated existing database, real external-executor fencing, and encrypted backup storage are not newly implemented by these test fixtures. Raw formulas remain local quarantined evidence, not ordinary SQL/FTS/agent-memory input; post-read checks do not prevent earlier Google-side execution. No real credentials, customer records, local databases, WAL/SHM files or evidence-vault objects are distributed.

The original 109 planning obligations remain in the retained baseline. This report maps new measured paths to evidence; it does not label all 109 gates passed because one related test exists. “Zero” describes observed forbidden outcomes in this finite fixture under its explicit oracle, not an unqualified theorem over all storage devices and remote services.

## 11. Reproduce on ZION and deploy deliberately

From the extracted release with the intended interpreter:

```sh
python3 -c 'import platform,sqlite3; print(platform.platform(),sqlite3.sqlite_version); assert platform.system()=="Darwin" and platform.machine()=="arm64"; assert sqlite3.sqlite_version_info >= (3,51,3)'
python3 -m pip install -r requirements-test.txt
PYTHON=python3 ./qualification/qualify_target.sh "$HOME/Library/Application Support/SovereignCRM/CRM-Qualification/$(date +%Y%m%d-%H%M%S)"
```

The target script uses fresh synthetic directories, runs the real regression suite, the full matrix, independent trace/storage checks, streaming and authenticated-RPC cases, adversarial/crash cases, and repeated search measurements. It does not contact Google or touch an existing lab authority. It retains the matrix's temporary fixture root for audit. **Do not use compatibility-only mode to satisfy target admission.** A newer standalone SQLite shell does not change the library linked into Python.

`docs/QUICKSTART.md` gives the minimal fresh-ledger deployment sequence and `docs/DEPLOYMENT.md` supplies the existing cloud provisioning contract. Keep live files outside Drive and use the provided router snippet instead of overwriting Antigravity's existing `./lab`. Real cloud principal, quota attribution, permissions, unattended token renewal, intended empty workbook and optional ingress execution need their own disposable-resource evidence.

## 12. Release files and integrity scopes

The package includes the runnable CRM, source-preserved Apps Script, old and new schema/contracts, all qualification runners, polished README/quickstart, the byte-preserved prior bundles, and both positive and adverse evidence. The most useful audit entries are:

| File | Evidence |
|---|---|
| `qualification/evidence/full/matrix_results.json` | Main workload, integrity, quota and partition measurements |
| `qualification/evidence/full/operation_trace.jsonl.gz` | All 50,000 original packets, outcomes and timings |
| `qualification/evidence/full/audit_trace.jsonl.gz` | All 190,000 original transaction/event frames with exact JCS bytes |
| `qualification/evidence/full/batch_trace.jsonl.gz` | Complete-batch identities, counts, sizes and provider application times |
| `qualification/evidence/full/fault_trace.json` | Injected 429 and lost-response events |
| `qualification/evidence/adversarial/adversarial_results.json` | LWW order permutations, claim races, process exits and negative controls |
| `qualification/evidence/streaming/streaming_results.json` | Real accepting/publication overlap |
| `qualification/evidence/rpc/rpc_results.json` | Real socket contention and exact retry results |
| `qualification/evidence/release_tests.xml` | Final Python test inventory and status |
| `qualification/evidence/final_node.json` | Apps Script checks and service-mock scope |
| `qualification/release_status.json` | Final machine-readable admission boundary |

`MANIFEST.sha256` covers every other archive member. The report header's body digest covers bytes after its one standalone receipt delimiter through EOF. The detached report checksum covers the complete Markdown including the header. The ZIP checksum is detached. `06_Delivery_Receipt.json` is produced only after upload/readback, outside the ZIP, avoiding a circular checksum. It records transfer verification, not an unrun deployment certification.

## Primary references and baseline attribution

[B5] The unchanged Turn 5 report and archive under `baseline/`, with the exact hash in section 2. [B4] The retained cumulative Turn 4 specification. [B3] The retained Turn 3 kill-gate analysis. Baseline statements are attributed; the new LWW and jitter behaviors are explicit release amendments.

[S1] SQLite, **Write-Ahead Logging** — https://sqlite.org/wal.html (checked 24 September 2026). One-writer/local-storage premises and the documented WAL-reset fix. This reference is not a test result for this host.

[S2] Google, **Sheets API usage limits** — https://developers.google.com/workspace/sheets/api/limits (checked 24 September 2026). Separate default read/write project/user quotas, atomic batches, request sizing and backoff guidance. The fake-provider timing and failures are our fixture, not Google's service observations.

[S3] Leslie Lamport, **Time, Clocks, and the Ordering of Events in a Distributed System** — https://www.microsoft.com/en-us/research/publication/time-clocks-ordering-events-distributed-system/ (primary publication record checked 24 September 2026). Logical ordering background; the register proof and restrictions are reasoned and tested in this report.

[S4] SQLite, **FTS5 Extension** — https://sqlite.org/fts5.html (checked 24 September 2026). Lexical indexing/ranking interface; no inherited sub-millisecond application guarantee.
