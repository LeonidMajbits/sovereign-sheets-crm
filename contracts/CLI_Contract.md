# Turn 4 — CLI contract

## Deterministic CLI contract

The executable remains `tools/crm-lab.py`, routed by the existing `./lab` command. This document specifies its future behavior; no CLI executable is included. It talks to the already-running, authenticated local broker and its selected tenant. It does not become a second database writer, spawn a new manager, or obtain Google credentials for a subagent.

### Grammar and result framing

Required forms are exactly:

```text
./lab crm list [--campaign <id>] [--status <state>]
./lab crm ingest <entity.json>
./lab crm sync [--push | --pull | --dry-run]
./lab crm query "<search-term>"
```

Additional bounded read options are `list [--kind <kind>] [--limit <1..200>] [--cursor <token>]`, and `query [--scope entities|interactions] [--fuzzy] [--limit <1..20>]`. Default list limit is 50, default query limit 20 and default scope entities. Fuzzy search applies only to entities. A repeated singleton option, unknown option, invalid combination or missing argument is a usage error. `--push`, `--pull` and `--dry-run` are mutually exclusive; an omitted mode means a bounded pull/capture pass followed by eligible publication. Optionally `--format table` selects escaped human-readable output for reads; JSON is the default regardless of TTY detection.

Three support reads are part of the contract: `show <entity-id>`, `audit <operation-id>` and `health`. Show supplies current typed state plus a verified base reference; audit supplies an authenticated prior operation outcome; health supplies freshness, active holds and deployment capability evidence. Claims, patches, resolutions and commercial changes use the same `ingest` command envelope rather than an expanding set of inconsistent mutation shortcuts.

Every successful or handled-failure invocation writes exactly one UTF-8 JSON object plus LF to stdout. It contains `schema_version` = `crm.result.v4`, `command`, `ok`, `outcome`, `error`, `tenant_id`, `ledger_id`, nullable `operation_id`, `as_of_commit_seq`, `data`, `sync`, and nullable `next_cursor`. `error` is null or an object with `code`, `retryable` and a bounded escaped message. `sync` always contains `state`, `published_commit_seq` and `pending_transactions`; unknown counts are null, not zero. Counters and monetary integers serialize as decimal strings. Business text remains escaped JSON data. Diagnostics go to stderr; no logs, banners, colors, credentials, raw quarantine, or prompts contaminate stdout. Runtime elapsed timings are optional diagnostics and excluded from deterministic content digests.

The same state, request and pinned normalization/search generation yield the same ordered business results; wall-clock diagnostics and invocation IDs are not promised byte-identical. A protocol outcome and its exit code must agree.

| Exit | Meaning |
|---:|---|
| 0 | Requested read/plan completed, or mutation COMMITTED locally / SATISFIED_NO_CHANGE; for sync only, selected target work is verified complete |
| 2 | Invalid command syntax/options |
| 3 | Invalid JSON/schema/type/field value; no accepted business effect |
| 4 | Authentication, capability or permanent cloud grant denial; AUTH_BLOCKED where applicable |
| 5 | Conflict, missing identity, BASE_UNAVAILABLE or CURSOR_STALE; caller must inspect/rebase deliberately |
| 6 | Bounded local contention; no terminal business outcome yet; retry the same operation identity |
| 7 | Integrity, unsupported linked runtime, schema-generation or layout failure requiring hold |
| 8 | Unsupported command/profile/feature, not a fallback to a different writer |
| 9 | Ambiguous external effect / UNKNOWN; never retry under a fresh business identity |
| 10 | Eligible operation incomplete: pending publication, quota hold, capacity backpressure or missing recovery resource |
| 11 | Local I/O or evidence-storage failure; no false COMMITTED acknowledgment |
| 130 | Interrupted; inspect the operation identity before deciding whether a mutation committed |

Local mutation success with cloud work pending still exits 0: its `sync.state` describes that lag. A `sync` call with pending work exits 10, not 0. A prior COMMITTED operation retried after cloud failure returns its original local outcome. A cloud AUTH_BLOCKED result cannot retroactively revoke that committed operation.

### list and show

Reads never access Google. They use a bounded SQLite read transaction. The selected tenant comes from authenticated local configuration; no argument is interpreted as a database path. `--campaign` requires an exact canonical ULID and uses the full campaign-membership relation, not only the displayed primary campaign. Unknown campaign or entity returns NOT_FOUND. A status valid for no selected kind is a schema error, not a silently empty result.

By default, list excludes tombstones/merged-away entities but includes both active and terminal current entities; the optional status/kind filters narrow it. Order is `(entity_kind, entity_id)` ascending under binary identifier comparison. Pagination is keyset-based. A cursor binds ledger, tenant, normalized filters, limit, query version, base commit and last key under broker authentication. If state has advanced since that cursor and the implementation cannot reconstruct the same snapshot, return CURSOR_STALE rather than pretending to continue an unchanged result set. No long-running SQLite read transaction is retained across CLI invocations.

Show includes canonical facets, relationships needed to understand the item, `entity_rev`, field/guard stamps, `state_digest`, current authority epoch and `{commit_seq, transaction_digest}`. It does not expose signing keys, arbitrary SQL or rejected raw evidence. Immutable legacy identifiers resolve through the explicit mapping; a merged identity reports its recorded survivor, not an invisible identity substitution.

### ingest

`entity.json` is a command packet, not a raw table dump or generic entity upsert. Accept one UTF-8 object, at most 65,536 bytes; reject BOM, duplicate keys, invalid Unicode scalars, trailing content, arrays and unknown fields before business interpretation. Validate `schema/ingest_command_v4.schema.json`, then byte lengths, signed-64-bit bounds, timestamp validity, enums, capability and template semantics. JSON Schema's character lengths/patterns are not a substitute for these predicates.

The caller supplies a stable ULID `operation_id`. No timestamp, status, owner or key in the file grants authority. The broker derives the authenticated actor and selected tenant from its connection. A file claiming a different tenant or ledger is rejected. The packet carries `schema_version`, `operation_id`, `tenant_id`, `ledger_id`, decimal-string `authority_epoch`, `template_version`, a verified `base` or permitted null, `command_type`, and typed `payload`. All are required; defaults are limited to explicitly defined create-time domain values.

A new independent entity can be created with base null. Any create referencing existing parents, actors assigned to work, plans, opportunities or channels must carry a reconstructible base and pass the dependency template. Artifact registration without a business parent may use the genesis base (commit zero and zero head digest) if that base is authentic to this ledger. Existing-object mutation always supplies a base; it is not silently refreshed to current values.

The broker first authenticates, then resolves the operation-ID/digest outcome, then evaluates a genuinely new command. Identity reuse with changed semantic bytes is rejected. A successful accepting transaction writes canonical facets, immutable version snapshots, field/guard changes, outcome, audit, approved search projections and outbox together. Nothing is published by the CLI itself. COMMITTED means local durable acceptance, not message delivery to a patron, a contract signature, or Google publication.

### sync

A call joins the existing publisher's bounded work request; it does not start an independent transport loop. The command selects current pending-through watermarks on entry, performs at most one bounded capture slice and one eligible publication batch, and reports what remains. Normal operation continues under the existing runtime lifecycle, not a promise by this planning document to perform background work.

`--pull` can read Google and commit captured metadata/observations locally. It performs no Google writes and no automatic adoption of raw human inputs. Capturing an observation can create a local audit/outbox obligation. `--push` permits prerequisite safety/verification reads but does not import or adopt new human proposals as business changes. If a required unsaved discrepancy prevents safe publication, it holds instead of overwriting it.

`--dry-run` is strictly local and read-only: no network call, token renewal, quota reservation, cursor advancement, evidence write, maintenance change or outbox mutation. It returns the plan implied by the last verified local state, marks cloud facts as possibly stale and does not call itself a connectivity test. A diagnostic requiring network access belongs to an explicitly admitted health check, not dry-run.

No network I/O occurs while a SQLite write transaction is open. Physical calls obey the shared scheduler, attempt journal and UNKNOWN holds. An interrupted request does not erase the attempt record. A synchronization result reports entry target, verified-through sequence, remaining count/bytes, current generation and hold reason; it never declares global emptiness while concurrent work is arriving.

### query and performance claim

A query is at most 256 UTF-8 bytes and eight lexical tokens, with at least one searchable token. The default grammar is literal token-AND matching through the configured Unicode61 tokenizer. Raw operators, column selectors, quotes and stars do not become executable FTS grammar; the future compiler either treats them as literal text or rejects an unrepresentable query with a named validation result. Exact ULID/qualified identifier lookup is tried first. Optional fuzzy matching follows the bounded candidate contract in [B02], never an automatic identity merge.

Scope entities queries `entity_fts`; interactions queries `interaction_fts`. Results join current canonical state before applying pagination or exposing snippets. Lower FTS5 BM25 scores rank first; ties use immutable identity. Scores are lexical ranking values, not calibrated identity probabilities. Normalization, tenant boundary and search generation are fixed in the response. Rejected raw observations never appear in either index. [S05]

**The new sub-millisecond requirement is a release gate, not an accomplished result:** warm SQL FTS execution, canonical join and first 20 rows must achieve p95 <1.0 ms in the fixed 1,000-entity / 3,000-alias-channel / 50,000-interaction fixture. Full warm broker retrieval including query normalization and ranking retains p95 <5 ms. Cold Python launch, IPC, JSON serialization, terminal rendering and network have separately reported end-to-end timings. Measure 2,000 queries per class after declared warm-up, repeated runs, p50/p95/p99/max, hardware/library versions, common-token and concurrent-writer cases. Exact, entity FTS, interaction FTS and fuzzy measurements remain separate. No performance badge is released when the relevant gate fails or has not run.
