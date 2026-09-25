# Turn 4 — Optional Apps Script ingress

## Standalone Apps Script webhook and deployment specification

### Profile boundary

The required `strict_direct` profile retains Turn 3: one home broker/publisher uses the direct Sheets API and authenticated bounded scans. Apps Script is absent from that profile's correctness path. The requested `optional_ingress` profile adds a standalone Apps Script project solely to accept transport deliveries and emit edit hints into a pinned Drive staging folder. It has **no canonical Sheets publication role, no commit authority and no failover role**. Direct publication and optional ingress may coexist because they do not compete to write canonical cells.

This is a standalone handler contract, not runnable `.gs` source. No script, deployment, trigger, folder, credential or OAuth grant is created in this planning release. The DDL exception does not authorize a webhook prototype.

### Entrypoints and ownership

| Future entrypoint | Invocation | Required effect | Return |
|---|---|---|---|
| `doPost(e)` | HTTPS POST to deployed web app | Authenticate and validate bounded envelope; create an immutable staging delivery; return its receipt | JSON TextOutput; normal handled response reaches final HTTP 200 |
| `doGet(e)` | HTTPS GET | Fixed non-sensitive protocol/health label only; no tenant data, keys or mutations | JSON TextOutput |
| `captureEdit(e)` | Explicitly installed spreadsheet edit trigger in standalone script | Stage a metadata-only dirty-range hint | Void; there is no HTTP response |
| `captureChange(e)` | Explicitly installed structural-change trigger | Stage a metadata-only layout-dirty hint | Void |
| `provisionIngress` | Authorized provisioning action, not runtime retry | Validate pins/scopes, install each expected trigger once, record deployment identity | Provisioning receipt |

An installable edit trigger is configured through the `onEdit` trigger type but targets `captureEdit`; merely naming a function `onEdit` in an unrelated standalone project does not establish the required authorized Drive-writing path. Installed triggers run as their creator, can call authorized services and are not a complete API/script mutation feed. Standalone-script access requirements must be verified for intended editors. [S13, S14]

### Fixed deployment configuration

Configuration pins `profile`, tenant/ledger IDs, allowed workbook resource IDs and numeric sheet IDs, projection generation, layout digest, private staging folder ID, command-protocol version, deployment audience, gateway signer key IDs, per-sender allowed capabilities, body limit and capture limits. No request can select a folder, spreadsheet, user, tenant or URL merely by including it in JSON.

Proposed logical staging location is `Sovereign_Google_Sheets_CRM/_staging/ingress/`. The actual folder ID is provisioned and stored outside cell content; a macOS Drive-sync path is not usable as a server-side Google resource identifier. The source folder verified for this specification does not prove the future service account or script owner can write the staging child.

Scope contract: spreadsheet read access for the optional trigger/hint profile, explicit Drive file creation/read access for the staging transport, and Script service authority to install its triggers. Where the selected APIs cannot restrict Drive OAuth to an arbitrary pre-existing folder, document the broader scope and reduce the owner's account/file permissions; do not call a broad OAuth grant folder-scoped simply because configuration pins one folder. Publication permissions remain with the home principal, not the webhook. The exact minimal granted scopes and account-policy availability are deployment gates. Secrets live in protected script properties/host key storage, never source bundles or staging packets. Script editors are trusted administrators.

The bridge uses a versioned `/exec` deployment, not a development `/dev` endpoint. Owner execution and permitted caller access must be explicitly configured. A publicly reachable deployment with HMAC access control is not a private network service, and HMAC cannot eliminate invocation-quota denial of service. Permission revocation produces an ingress hold; strict direct operation remains independent. Initial administrative consent is provisioning, not an automated browser-login repair loop. [S12, S17–S19]

### Exact transport object and authenticated bytes

The HTTP body is one UTF-8 JSON object, maximum 98,304 bytes including the nested command and authentication metadata. Allowed top-level fields are `protocol` = `crm.ingress.v4`, `kind` = `command` or `dirty_hint`, `delivery_id`, `sender_key_id`, `audience`, `tenant_id`, `ledger_id`, `issued_at`, `expires_at`, `nonce`, `payload`, `payload_digest`, and `mac`. Unknown fields, duplicate keys, invalid Unicode, non-finite numbers and noncanonical numeric encodings are rejected. IDs are ULIDs, digests/MAC lower-case 64-hex, times UTC milliseconds, nonce 32 random bytes encoded as 64 lowercase hex. Command payload is exactly the v4 command object; a dirty hint has the metadata schema below.

Use RFC 8785 JCS and HMAC-SHA-256 over the complete envelope except `mac`, prefixed by ASCII `CRM3:transport:v1` plus LF, retaining Turn 3's domain separation. Bind the sender to a server-owned tenant/audience/capability map. Accept transport lifetime at most 300 seconds and bounded 60-second skew; the command's historical base is not renewed with its transport timestamp. Fresh retransmission may use a new delivery/nonce, but its operation identity and semantic bytes do not change. [S23, S24; B03 §5]

JSON parsing must detect duplicate keys before ordinary `JSON.parse` can discard them. The implementation must supply a tested duplicate-aware decoder and JCS serializer, not claim `JSON.stringify` alone is JCS. HMAC comparison must avoid data-dependent early-return equality where supported; arbitrary Google headers are not assumed accessible from `e`. The home authenticates the original sender envelope independently, and records that sender, not just the gateway creator. Transport retries already staged are authenticated at their recorded admission time; a legitimately delayed four-hour delivery is not discarded merely because the original transport timestamp has since expired. A never-admitted expired packet still fails admission.

A gateway-signed custody record binds original payload digest, sender, delivery, observed admission time, protocol, tenant, ledger and immutable Drive file identity where known. The gateway receipt does not attest that the human named in a cell really authored it. A compromised authorized gateway remains a trust boundary; there is no claim that a shared-secret MAC proves authorship against every key holder.

### doPost processing contract

Authenticate and bound the request before interpreting intended business changes. The process is: validate envelope structure and exact bytes; resolve key/audience/tenant; verify MAC and time window; enforce sender/capability/template restrictions; validate command payload or dirty-hint schema; reserve gateway-local admission; create one staging delivery with immutable content; confirm the returned Drive ID and readable digest; then return an intake receipt. Every step has a terminal named failure or an explicit uncertainty result. No SQL, URLs, formulas, tools, or instructions contained in a field are executed.

Command intake may stage structurally valid authorized **proposals**, not accepted canonical data. It does not reconstruct a base from current Sheets. A raw `human_note` is not wrapped as an authorized command. Explicit formula-valued and rejected raw cell data are never staged as ordinary text. Arbitrary evidence bodies are disallowed; only approved, bounded literal fields from the signed command schema or safe references can pass. Semantic poisoning remains a downstream data/capability boundary even when the string passes this gate.

For a new accepted transport delivery, create a file named `<delivery_id>.crm-ingress.json`, media type `application/json`, under the pinned staging folder, containing original authenticated command plus signed custody metadata. Filenames are diagnostic only; Drive ID, validated payload digest and operation identity establish the record. A lost file-create response is UNKNOWN; a retry may create a duplicate file, but never a second canonical effect. Duplicate filenames are allowed and are not resolved by overwriting the first search result. No rename/append-overwrite protocol is needed for a small single-file delivery. [S20–S22]

A successful handled response has exactly `protocol`, `ok`, `state`, `delivery_id`, nullable `operation_id`, nullable `file_id`, `payload_digest`, `received_at`, and nullable `error_code`. State is `RECEIVED`, `REJECTED`, `RETRYABLE_NOT_RECEIVED`, or `UNKNOWN`; only RECEIVED has `ok=true` and a verified file ID. Add `receipt_mac` binding all these fields under the configured gateway receipt key and domain `CRM4:ingress-receipt:v1` plus LF. A rejected unauthenticated request gets only a generic non-sensitive error response with no prior operation data. The caller retains its original packet until it observes the home outcome, not merely HTTP200.

Apps Script's documented TextOutput interface does not expose arbitrary HTTP status/header setters. Therefore a normally handled application rejection may also arrive with HTTP200 and `ok=false`; callers must inspect the authenticated body. Platform-level denial, timeout, redirect failure or quota failure can produce a different status or HTML. **Do not promise 200 for every possible request, and never return RECEIVED before durable intake.** Follow Content Service's expected response redirect without forwarding application secrets to an arbitrary redirect destination or replaying the original POST as a fresh mutation. [S12, S15, S16]

### Installed edit/change behavior

The trigger path produces hints, not full mutation bodies. A dirty hint contains only `workbook_id`, `sheet_id`, `generation_id`, bounded zero-based `start_row`, `end_row_exclusive`, `start_column`, `end_column_exclusive`, `change_class`, `captured_at`, and nullable trusted-event trigger identifier. It contains **no cell value, oldValue, computed result, formula, note, editor-supplied role or arbitrary URI**. Strip unavailable event attributes; an unavailable editor remains unknown. For huge pasted ranges, emit one whole-sheet dirty marker rather than serializing thousands of values. The home scanner later reads bounded typed CellData and applies the Turn 3 local evidence policy. [S11, S14]

This narrows Turn 2's optional direct `_Ingress` capture to preserve Turn 3's rule that rejected raw formula bodies never enter Drive staging. Optional hints can be coalesced or lost under trigger limits because mandatory periodic typed scans remain the correctness path. A trigger that failed to stage a hint cannot claim that an edit was durably captured. No synchronous waiting for the home, no sleep-based quota recovery, no modification/clearing of `human_status` or `human_note`, and no edits to the three canonical boards are permitted.

Use a short script lock only to serialize cooperating admission/config bookkeeping. It does not fence humans or the home publisher. Limit controlled bridge staging to 10 files/minute per deployment with burst capacity 2; this is a design budget, not a stated Google quota. Dirty events coalesce by workbook/range; command senders receive explicit retryable intake failures and retain their packet. Maintain bounded recent-admission state in script properties; never store the durable command queue there. Restart/unknown budget state waits conservatively before admissions. Apps Script/service-account calls must be attributed to their actual consumer project and principal; independent Drive quotas are monitored separately from Sheets read/write counters. [S17]

### Home consumption and recovery

List only the configured staging parent, follow every provider page token, verify returned parents/type/size, fetch bounded complete bytes and verify original sender MAC plus custody, tenant, ledger and protocol. A name, timestamp or list order is not acceptance. Record each fetched Drive ID and payload digest in `staging_receipts` in the same local transaction that persists its command outcome or a durable unbased/invalid-input disposition. Changed content under a known ID is a quarantine incident. Duplicate file IDs/payloads are idempotent observations, not duplicate domain mutations.

A page token does not provide a stable database snapshot of a mutating folder. Use overlapping enumeration and periodic full bounded sweeps of the live intake set. Do not rely solely on a last filename or modified-time maximum. Retain a compact ID/digest receipt permanently; retire processed staging files only after verified home receipt and declared archive coverage. The default release makes retirement a separately authorized maintenance action rather than an automatic deletion job. The normal intake set is capped at 10,000 unretired files or 256 MiB, with admission backpressure. Exhausted intake capacity cannot discard accepted home history.

For based commands, the home applies its original ancestry checks; receiving them hours later does not renew the base. Dirty hints only mark bounded scanner work. A staged command cannot inject a different server-owned read/write dependency set. Raw observations must be adopted separately by an authorized resolver. Replayed expired transport already recorded as admitted can return its existing result; it cannot mint a new operation with changed bytes.

### Deployment acceptance

Before enabling this optional profile, record the real script project/version/deployment IDs, creator identity, cloud consumer project, OAuth scopes, permitted access mode, staging ID/permissions, test workbook/generation and installed trigger IDs. Demonstrate one literal human edit creates a metadata-only hint, one API write does not rely on that trigger, one valid signed POST creates a readable exact packet, one duplicate produces a single home effect, one malformed/MAC-invalid packet creates no business input, and a lost create/response enters the correct uncertain state. Demonstrate revoked owner grants disable only ingress; no browser or automatic alternate publisher appears.

The test for 200 checks the final normal handled response, its JSON MIME/body and receipt identity. It also deliberately checks a normal application rejection with HTTP200, a platform error/HTML response and a redirect, so transport status cannot masquerade as business success. These tests are NOT_RUN in this planning release.
