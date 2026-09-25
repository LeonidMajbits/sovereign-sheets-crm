# Optional Apps Script ingress — actual Code.gs

Code.gs is executable V8 Apps Script source, not pseudocode. `tests/test_apps_script.js` executes it in Node with simulated Google interfaces; `tests/test_integration.py` verifies a Python-signed packet through that source and then independent Python custody validation. Live deployment/scopes/Google quotas have NOT been tested.

## Role

`doPost(e)` authenticates one bounded HMAC/JCS envelope, validates the frozen command alternatives/capability, creates a private immutable Drive staging file and verifies its bytes before returning RECEIVED. The receipt MAC binds the returned Drive ID. A staging wrapper contains the independently signed original sender envelope and gateway custody. The custody's file_id is null because the Drive ID does not exist before file creation; the response receipt binds it afterward. Delivery ID/payload/operation and actual fetched Drive ID establish deduplication. No filename uniqueness claim is made.

`captureEdit(e)` is installed using the onEdit trigger type. `captureChange(e)` handles structural invalidation. They stage metadata only: IDs, zero-based range, generation, change class and capture time. They do not read/copy `e.value`, oldValue, formulas or computed content. The home scanner is mandatory; missed hints do not grant a capture receipt or lose canonical state. Trigger callbacks do not return HTTP responses.

`doGet()` returns a fixed non-sensitive role/protocol label. There is no canonical updateCells, setValue, clearContent, Sheet formula evaluation, model call, browser repair or raw-evidence summarizer.

## Provisioning

An authorized administrator must create a standalone project, install Code.gs and appsscript.json, establish its OAuth grant, pin the intended workbook and private staging folder, set Script Properties and invoke `provisionIngress` once. Deploy the chosen `/exec` version under the selected owner/access policy. This build did not perform those steps.

Set `CRM_INGRESS_CONFIG` to a JSON object with:

- profile: optional_ingress; tenant_id, ledger_id, audience, workbook_id, generation_id.
- sheet_ids: exact five-tab name/numeric-ID map.
- staging_folder_id: already-provisioned private `_staging/ingress` folder ID.
- gateway_key_id and gateway_key_hex: protected independent custody/receipt key.
- gateway_sender_key_id: one configured sender permitted only dirty_hint for trigger use.
- senders: key ID -> `{key_hex, capabilities}` for each approved host/sender.

Configuration is bounded to 8 KiB and 32 senders; the gateway is not a 500-agent key registry. Aggregate remote commands per host and retain unsent packets on that host. Keys must be independently generated 32-byte secrets encoded as 64 lower-case hex. Never commit or paste real configuration into this bundle.

The host's private `ingress` configuration also contains the same scope pins and staging_folder_id; its `senders` map adds each independently provisioned actor_id, and `gateway_keys` maps approved gateway key IDs to their secrets. Server-side capabilities must agree with authenticated actors; a field in a packet never creates one.

The manifest requests Drive access, spreadsheet read access and script.scriptapp trigger-management access. Drive OAuth here is broad; pinning a folder in code does NOT make that OAuth scope folder-scoped. Use a restricted owner/account, explicit resource ACLs and minimum practical grants. Real authorization/access policy is a deployment gate. Apps Script editors are trusted administrators.

`provisionIngress` records bounded admission state and installs the two expected triggers idempotently. It refuses duplicate expected triggers. Normal operation has no re-consent or browser fallback. Runtime grant loss creates failure/hold; the direct publisher remains separate.

## Protocol details

The implementation uses duplicate-aware JSON and the integer-only RFC8785-compatible profile shared with Python. It rejects floats, unsafe integers, negative zero, invalid Unicode, duplicate keys, unknown schema fields and invalid MACs. Large counters remain decimal strings. Data text is not Unicode-normalized before signing.

Sender MAC domain: `CRM3:transport:v1` + LF. Gateway custody: `CRM5:custody:v1` + LF. Response receipt: `CRM4:ingress-receipt:v1` + LF. Use the exact canonical objects in the source and schema manifests. Transport lifetime is <=300 seconds with 60-second skew; a staged packet delayed four hours is validated at its authenticated custody-admission time, without renewing its business base.

Admission reserves a conservative 10 files/minute with burst 2/second. At 10,000 unretired/reserved files or 256 MiB, intake holds. The original sender retains commands until home outcome, not merely HTTP200. Unknown create outcomes consume capacity conservatively. Administrative retirement/capacity reconciliation is not a automatic deletion job.

A normal handled doPost response reaches HTTP200 but may contain ok=false. Only RECEIVED with verified file identity means durable intake; it still is not COMMITTED. Platform errors, HTML, quotas or redirect failures need not return 200. Apps Script TextOutput does not supply arbitrary status/header setters. No implementation promises success from the transport code alone.

Raw formula/effective-only input is inspected later in typed Sheet scans and retained only in the home evidence vault. This prevents local data laundering, not a formula request that Google might already have executed. Sheet readers must already be authorized for everything disclosed in that workbook.
