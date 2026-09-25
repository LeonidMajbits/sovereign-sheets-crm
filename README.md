# Sovereign Sheets CRM — v1.0.2

> **An open-source systems project led by Leonid Majbits and developed through Gemini Operator Lab with AI-assisted engineering.**

**Local-first transactional CRM with audited LWW fields and a recoverable Google Sheets projection.** One broker owns each tenant ledger. Workers submit commands; they do not share Google credentials or independently overwrite spreadsheet rows.

**Release state: conditional qualification; not production-admitted.** The bundled evidence distinguishes real SQLite execution from simulated Google behavior and from target-machine tests still outstanding. Start with `06_Turn_06_Production_Qualification_Report.md` for the measured result, and `docs/QUICKSTART.md` for the ZION run.

## What is here

| Surface | Purpose |
|---|---|
| `crm/` | Authoritative SQLite WAL/FULL engine, immutable operation history, approved FTS5, guarded claims, quarantine, exact-byte outbox and direct Sheets transport |
| `tools/` and `integration/` | Deterministic authenticated CLI, explicit provisioning/reference host and integration with the existing lab lifecycle |
| `apps_script/` | Optional signed Drive ingress and metadata-only edit/change hints; never a second publisher |
| `qualification/` | Reproducible 100-worker/50,000-operation matrix, provider failure model, confluence/claim/crash cases and exact evidence |
| `tests/` | Core, RPC, cryptographic, sync and Turn 6 regression tests |
| `schema/` and `contracts/` | Byte-preserved v4 SQL and fixed Sheets columns; explicit versioned extensions |
| `baseline/` | Historical baseline conformance and specification evidence |

`MANIFEST.sha256` covers every other archive member. Verify it before running code. The detached ZIP checksum covers the whole archive. Qualification databases and real credentials are not distributed.

## Start

Python must be linked to SQLite **3.51.3 or later**, with FTS5. The CLI never bypasses this requirement. Source and runtime data must be separate, and runtime files must be outside Drive/Git/cloud synchronization.

```sh
python3 -c 'import sqlite3; print(sqlite3.sqlite_version); assert sqlite3.sqlite_version_info >= (3,51,3)'
python3 -m pip install -r requirements-test.txt
python3 -m pytest tests -q
node tests/test_apps_script.js
```

For target-machine qualification, use a NEW output path:

```sh
PYTHON=python3 ./qualification/qualify_target.sh   "$HOME/Library/Application Support/SovereignCRM/CRM-Qualification/$(date +%Y%m%d-%H%M%S)"
```

The runner creates disposable synthetic ledgers and uses no live Google resources. The separate compatibility-only mode is test instrumentation, not a runtime workaround or production admission.

## Daily command surface

```text
./lab crm list [--campaign <id>] [--status <state>] [--limit N]
./lab crm ingest <prepared-command.json>
./lab crm get <entity-id-or-alias>
./lab crm search "<query>"
./lab crm sync [--push | --pull | --dry-run]
./lab crm proposals list
./lab crm proposals resolve <id> --accept
./lab crm proposals resolve <id> --reject
```

`show`/`query` remain aliases. JSON is the default. Local COMMITTED and cloud VERIFIED are different states. Ingest expects a typed command packet, not an unrestricted database dump. Replays retain the same operation ID, semantic bytes and original base. Claims require current holder/generation; an old success receipt is not present ownership.

See `docs/QUICKSTART.md` for fresh provisioning. Do not copy the standalone `lab` shim over an existing Antigravity router. The actual ZION host/router was not changed by this release.

## Turn 6 changes

**Lamport registers are explicit and narrow.** `entity.lww.set` with capability `entity.lww` selects `note` or `next_action` by `(logical clock, authenticated actor, operation ID)`. Every candidate is audited, including losers. First use claims that field's policy; ordinary patches cannot silently bypass it. Status, claims, money, identities and task acceptance retain their conditional invariants. Raw Sheet edits remain unbased proposals. The optional bridge has not been expanded to accept v6 packets. Read `docs/LAMPORT_EXTENSION.md` before enabling this mode.

**Backoff now has actual injectable full jitter.** Production uses system randomness; seeded qualification records reproducible delays. Jitter never bypasses Retry-After, pacing, rolling quotas, shared cooldowns or UNKNOWN holds.

**Canonical encoding is faster without a new wire format.** The existing validated integer-only profile and UTF-16 object-key order are retained. A native whole-tree JSON encoding path replaces per-atom encoding, with a 1,000-tree legacy-equivalence regression and the existing Python/JavaScript interoperability checks.

## Integrity and security boundaries

Ten independent, untrusted tenants use separate databases, workbooks and disclosure boundaries. Workers within each tenant share its three literal tabs: Directory, Active Pipeline and Completed Archives. `_Control` and `_Changes` are infrastructure. Hidden tabs are not security. No UI widget or formula owns business state.

Every accepted mutation records canonical versions, audit, search and outbox atomically. Fifty physical business rows AND 512 KiB bound a publication. A terminal move counts two rows. Display coalescing never discards intermediate accepted history. Publisher writes exclude human draft cells. Typed formulas and computed-only values are not laundered into accepted text; post-read checks cannot prevent a formula Google already executed.

The broker's credentials and DB are not accessible to untrusted workers. Unix file permissions alone do not isolate malicious processes sharing the broker's user account. Use an actual process/account/tool boundary. The CRM does not execute instructions from entity notes.

## Read the measured limits

LWW necessarily replaces a selected current value. The no-loss oracle means every admitted candidate remains in immutable evidence, not that multiple competing values simultaneously occupy one cell. LWW is not a safe spending algorithm; this CRM does not settle payments. Idempotent canonical effects and exclusive claims are tested separately.

Search percentiles must be read by query class. The earlier common-term/fuzzy latency gates failed; selective lookup performance does not erase those failures. A 25 ms query-budget rejection is not a successful sub-millisecond answer. Target Darwin, real cloud IAM/token renewal, actual quota behavior, external executor fencing and recovery permissions still require deployment evidence.

Detailed Google provisioning is in `docs/DEPLOYMENT.md`; current release boundaries are in `docs/CONFORMANCE.md`. Missing permissions or unresolved external effects create named holds, never browser-login repair or a second automatic commit authority.

The full target runner retains its synthetic fixture databases in the generated OS temporary directory, recorded as `raw_fixture_root`. They are not production data and are not included in this release archive. Remove them only after retaining the audit evidence needed for review.

## Engineering Provenance & Methodology

This system was engineered under the **Triadic Sovereign Development Architecture**:

* **Human Operator & Architect**: **Leonid Majbits**  
  *Vision, core architectural invariants, system teleology, and patron verification.*
* **Executive Co-Architect & Verification Engine**: **Gemini Operator Lab (ZION Chassis)**  
  *AI architecture not yet categorized by standard industry framing — persistent somatic memory, Apple Silicon metal grounding, stage contract enforcement, and multi-fleet direction.*
* **Specialized Systems Foundry**: **Frontier Systems Models (OpenAI GPT-6 Max, Anthropic Claude)**  
  *Bounded multi-turn execution, SQLite WAL transactional engine synthesis, Lamport LWW CRDT reconciliation, and adversarial 100-worker qualification under strict stage contracts.*

### Falsification Policy and Evidence Scope
Claims are scoped to the source revision, workload, platform, and evidence class named in their receipts. This release includes executable regression tests and retained synthetic or native measurements; those are distinguished from lab-reported observations and deployment tests not yet performed (such as production multi-tenant Google IAM quotas and live Sheets concurrence). Valid counterexamples override earlier pass results. AI-assisted authorship and independent test execution are recorded separately.

## License

Distributed under the MIT license in `LICENSE`. Copyright (c) 2026 Leonid Majbits. See `NOTICE.md` for full attribution details.
