# Sovereign CRM Lab — 0.5.0rc1

**Actual Python engine, authenticated local CLI, literal Google Sheets publisher/scanner, and optional Apps Script ingress.** This is an implementation candidate with executed local tests, not a certificate that the live Google deployment or Darwin performance gates passed.

Start with `05_Turn_05_Production_Implementation_Report.md` for evidence and limits. `MANIFEST.sha256` covers every other file in this archive. The unchanged cumulative Turn 4 archive is in `baseline/`.

## Non-negotiable operating boundary

One tenant-isolated `crm.db`, one home broker, one cloud publisher. A client cannot select a database path, acquire Google credentials, or become a second writer. Raw Sheet edits become observations; they never overwrite the canonical database automatically. Claims are on dispatch attempts, not external conversation IDs. No automatic lease stealing or second-home promotion exists.

The live database, WAL/SHM, prepared requests, keys and evidence must be outside the source repository and all synchronized folders. The code rejects known synchronized paths, the source bundle itself and Git-root descendants. This is a guardrail, not a filesystem mount detector: deployment must still establish that the chosen physical volume is local and unsynchronized.

The CLI authenticates with a per-principal local HMAC key. **0600 files do not isolate hostile processes running as the same OS user.** Agents with arbitrary same-UID shell access could read the keys/database. Use a restricted broker account, sandbox/tool boundary or equivalent process isolation. Do not give every subagent the generated operator key.

## Runtime and installation

POSIX host: macOS or Linux. Python >=3.11, Node 22 for the webhook harness, and the Python interpreter's **linked SQLite >=3.51.3**, with FTS5. The runtime deliberately refuses SQLite 3.46.1 even though the DDL compiles there. Installing a newer standalone `sqlite3` executable or merely adding `pysqlite3` does not change which library this code imports.

From the extracted code bundle:

```sh
python -c 'import sqlite3; print(sqlite3.sqlite_version); assert sqlite3.sqlite_version_info >= (3,51,3)'
python -m pip install -r requirements.txt
```

`requirements-lock.txt` records the dependency versions available in the validation interpreter, including test dependencies. They are test pins, not a security-audit assertion. No third-party libraries or credentials are vendored. International phone parsing is optional and fails explicitly until `requirements-phone.txt` is installed; that optional dependency was not available in this build's test environment.

## First local run

These commands provision **a fresh ledger only**. They never overwrite an existing database or migrate another project. Choose a dedicated local data root; do not use the Drive dropzone for runtime files.

```sh
ROOT="$HOME/Library/Application Support/SovereignCRM/CRM/primary"
python tools/crm-admin.py init --root "$ROOT" --actor-name "Leon"
export CRM_CLIENT_CONFIG="$ROOT/client.json"
python tools/crm-host.py --config "$ROOT/broker.json"
```

The reference host occupies that terminal. It is explicitly started for acceptance/use; the CLI does not launch it. In another terminal, with the same `CRM_CLIENT_CONFIG`:

```sh
./lab crm health
./lab crm list --limit 20
python tools/crm-make-command.py --command entity.create \
  --payload examples/new-person.payload.json --independent \
  --output "$ROOT/create-person.json"
./lab crm ingest "$ROOT/create-person.json"
./lab crm search "Synthetic"
./lab crm sync --dry-run
```

The example is labeled synthetic. `crm-make-command.py` creates a NEW packet and never ingests it. For a retry, resend the unchanged existing file; do not regenerate its operation ID or base. The maker refuses to overwrite a packet. Existing-entity commands use a verified current base by default; independent creation is an explicit option and still receives server-side validation.

The reference host adds no timer or new manager agent. For continuous operation, the existing lab lifecycle calls the publisher/scanner at its admitted cadence. `integration/embed.py` and `integration/lab_router_snippet.sh` expose that integration. **Do not replace an existing `./lab` file with this bundle's standalone shim.** No actual Antigravity runtime/router was inspected or modified during this delivery.

## CLI

```text
./lab crm list [--campaign <id>] [--status <state>] [--kind <kind>] [--limit N] [--cursor <token>]
./lab crm ingest <entity.json>
./lab crm get <entity-id-or-alias>
./lab crm show <entity-id-or-alias>
./lab crm search "<query>" [--scope entities|interactions] [--limit N] [--fuzzy]
./lab crm query "<query>" [--scope entities|interactions] [--limit N] [--fuzzy]
./lab crm sync [--push | --pull | --dry-run]
./lab crm proposals list [--limit N]
./lab crm proposals resolve <id> --accept [--operation-id <new-id>]
./lab crm proposals resolve <id> --reject [--operation-id <new-id>]
./lab crm audit <operation-id>
./lab crm health
```

JSON is always the default. Diagnostic messages go to stderr. `get` and `search` are the new aliases requested in Turn 5; `show` and `query` remain supported. Application-qualified exact channel searches are `email:LocalPart@example.com`, `domain:example.com`, and `phone:+<international number>` when the phone parser is installed. These return candidates, never an identity merge. Email local-part case/plus tags are not silently rewritten.

`ingest` takes the frozen typed v4 command envelope, not a table dump. All 19 v4 command templates are routed; `entity.tag.set` is an explicit additive v5 command. Tags are normalized relations and participate in approved lexical retrieval. Unknown fields/commands fail closed.

Proposal resolution records an explicit decision about particular captured bytes. Repeating the convenience command reuses its persisted first operation/base; it does not silently renew a conflict. An intentional rebase uses a new operation ID after inspection. Blank input is not a canonical clear. Canonical null clears use the typed command packet.

`--dry-run` is local and read-only: no network, token renewal, cursor movement or queue mutation. `--pull` performs a bounded typed scan/staging pass, with no Google writes or automatic adoption. `--push` permits prerequisite verification reads. One call does bounded work and returns pending/hold state; it is not an unlimited blocking queue drain.

Exit codes: 0 completed read/local commit; 2 usage; 3 schema/value; 4 auth/capability; 5 conflict/not found/stale cursor; 6 contention; 7 integrity/runtime/layout; 8 unsupported feature; 9 ambiguous external/local response; 10 pending/quota/query budget/capacity hold; 11 I/O; 130 interruption. A committed mutation can exit 0 while its cloud publication remains pending. A lost client response after sending a mutation returns UNKNOWN rather than claiming no commit occurred.

## Google Sheets deployment

See `docs/DEPLOYMENT.md`. No workbook, credentials, staging folder, Apps Script project or trigger was deployed during this build. The artifact files were uploaded to Drive; that is not a CRM integration test.

The normal data plane uses a dedicated service account. Its key is held only by the broker. The optional Apps Script path has an independent grant and is ingress-only. There is no OAuth browser-repair fallback.

The three visible tabs and their column order are unchanged from v4: Directory (31), Active Pipeline (37), Completed Archives (39). `_Control` (20) and `_Changes` (12) remain internal. Only Directory `human_status` and `human_note` are human proposal columns; every publisher plan excludes them. Pipeline/archive transitions count both physical rows. All machine values use explicit stringValue and TEXT formatting, including leading `=`, `@`, `+`, `-`. Formula-origin/effective-only input is quarantined, not evaluated or laundered.

A single batch respects **both** 50 physical business rows and 512 KiB of complete serialized request data. The load fixture may need more than the paper minimum of ten batches because complete audit and cell framing consume bytes. Intermediate accepted history is never removed to squeeze in another row.

## Verification

```sh
python -m pip install -r requirements-test.txt
python -m pytest tests -q
node tests/test_apps_script.js
python tools/benchmark_search.py --output search-benchmark.json
```

Tests create disposable local fixtures. When the test interpreter is older than the production floor, `tests/conftest.py` lowers the floor **only inside those fixtures**; a separate test asserts that the real production path refuses the old runtime before creating files. The benchmark has the same explicit temporary-only compatibility accommodation. There is no production bypass flag or environment variable.

The Python suite exercises actual SQLite WAL files, constraints, handlers, RPC/CLI, signed snapshots and fault-controlled provider interfaces. The Node suite executes Code.gs with simulated Google services and interoperates with Python HMAC/JCS. Neither is a live Google test. Full logs, machine-readable results, environment, source checksums and measured search percentiles are in `verification/`.

Selective lookup is fast; a blanket sub-millisecond promise is not released. Common-term ranked queries over 50,000 interactions and fuzzy retrieval are separately measured. Expensive ordinary queries have a cooperative 25 ms budget and return QUERY_BUDGET rather than partial results disguised as complete. This is not an OS hard deadline. Cold process/IPC cost and concurrent-writer behavior are distinct from warm SQL timing.

## Recovery and remaining gates

A found receipt only resolves a batch when complete intended contents match and exactly one possibly applied send is established. UNKNOWN work is not resent under a new identity. Restart puts uncertain publications and held claims into explicit recovery states. Claim recovery requires the host's real fencing verifier; by default it is unavailable rather than fabricated.

Signed snapshots include required database/evidence/prepared-request/artifact bytes and use an independently pinned Ed25519 verification key. They are plaintext local bundles with 0700/0600 permissions, **not encrypted backups**. Store them only inside an authorized encrypted volume or add an approved encryption layer before cloud storage. Automatic cloud upload of raw quarantine snapshots is not implemented.

Automatic replacement-workbook rotation, stale-authority promotion, migration of an independently existing database, and integration with the actual external model executor remain release gates. The current implementation holds those cases safely rather than inventing missing permissions or cancellation evidence. Read `docs/CONFORMANCE.md` before production admission.
