# Deployment and integration contract — Turn 5

## Private local authority

Use a supported Python-linked SQLite build, not merely a newer shell executable. Run `crm-admin.py init` only on a fresh private root. The code refuses known Drive/sync roots, source-bundle descendants and Git-root descendants. Real filesystem/storage classification and unattended reboot-time credential access are deployment checks; strings in a path cannot establish them.

The generated `broker.json` and `client.json` are mode 0600 and contain real locally generated secrets. Never upload them to the dropzone, source control or model prompts. Put untrusted agent processes behind a real OS/tool isolation boundary. Same-UID file permissions alone do not keep an agent with arbitrary shell access out of the database.

The existing lab actor registry must provision actor rows and server-side principal/capability bindings before an agent uses its own identity. This package's fresh provisioning creates the operator and runtime service actor; it does not guess the identities or rights of an existing fleet. The reference host accepts a private principal map. Client packets cannot assign themselves a role/capability.

The `quota_root` is one private shared operational directory for every controlled broker using the same actual Google principal/project. Its `quota.db` is transport bookkeeping, not a second business authority. A new quota file per tenant would violate the shared limit. The frozen in-ledger quota table is retained; the shared operational store is the explicit v5 cross-tenant implementation amendment.

## Required cloud configuration

Provision an unused spreadsheet accessible to the dedicated service account. This code does not assume the right to create My Drive files; the caller must provide the actual resource and grants. Record real consumer project and service-account email. The configured principal must match the credential's client_email.

Add a `cloud` object to the already-private broker configuration. The following is a TEMPLATE: angle-bracket strings are intentionally invalid until replaced; no sample credentials are usable.

```json
{
  "spreadsheet_id": "<ALREADY_PROVISIONED_UNUSED_SPREADSHEET_ID>",
  "generation_id": "<NEW_CANONICAL_ULID>",
  "sheet_ids": {
    "Directory": 0,
    "Active Pipeline": 101,
    "Completed Archives": 102,
    "_Control": 103,
    "_Changes": 104
  },
  "quota_root": "<PRIVATE_SHARED_QUOTA_DIRECTORY>",
  "consumer_project": "<ACTUAL_GOOGLE_CONSUMER_PROJECT>",
  "principal": "<SERVICE_ACCOUNT_EMAIL>",
  "service_account_file": "<PRIVATE_MODE_0600_CREDENTIAL_FILE>"
}
```

Directory's numeric sheet ID must be the sole existing blank tab's actual ID, not assumed 0. The other four IDs must be distinct unused nonnegative integers. The initial resource must have one GRID sheet, at most 1,000 rows and 64 columns, no merged cells and no entered/effective content, notes or unsupported cell objects. The header/bootstrap action refuses existing business data; it does not delete another tab to simplify setup.

Stop the reference host before explicit administration; a second authority cannot open the ledger:

```sh
python tools/crm-admin.py cloud-init --config "$ROOT/broker.json"
```

This is the first command in the instructions that can write Google. It journals exact bootstrap bytes locally, initializes the five literal tables in one structural batch, protects publisher-owned areas, verifies headers and explicitly activates the resource. Re-running a verified bootstrap does not create a second set of tabs. A lost response enters UNKNOWN and only read-reconciles. No browser sign-in, guessed sharing change, workbook copy, or blind retry is performed. Initial consent and permission assignment are administrative prerequisites, not something the CRM bypasses.

Start the existing runtime/reference host with that same private configuration. The normal publisher uses no hidden SDK retries. Internal scheduling limits are 30 Sheets reads and 20 writes per minute per principal/project, project total 240, and a 15-second write pacing lower bound; provider quotas and external shared traffic can reduce available capacity. A restarted scheduler conservatively waits a quota window when prior state exists. A sync call during that wait returns a named hold, not sleep inside a database transaction.

## Actual integration boundary

`integration/embed.py` constructs Database, Engine and Broker for the existing lifecycle. The host supplies a publisher factory, protected credentials, actor mapping, schema-approved artifact registry and, before claim recovery, its real executor-fencing verifier. Do not hand `ActorContext` construction or the database connection to an untrusted worker.

`integration/lab_router_snippet.sh` shows the one dispatch branch to add to the existing router. The delivered root `lab` is a standalone acceptance shim only. No repository/router file in the real Antigravity installation was read or edited here.

The host invokes bounded sync periodically through its existing scheduler. The reference host starts no background timer or new agent. Default sync performs one bounded scan and at most one eligible publication. Reads and business commits remain local when Google is unavailable and storage permits.

The publisher now sweeps last-verified active slots across all three business tabs in <=100-row slices. It compares canonical cells to last-verified shadows, not newer unpublished local state; raw inputs and drift are captured separately. At most 100 new observations are captured in a slice, with the cursor retained before an unfinished row. Row-identity discrepancies stop positional publication. Missing rows do not delete entities. Retired slots are not reused inside a generation.

## Optional Apps Script

See `apps_script/README.md`. The bridge stages authenticated command proposals or metadata-only dirty hints. It has no canonical Sheet write path. Its OAuth grant, script owner and Drive budget are independent from the direct service account. A revoked bridge grant does not grant fallback publication rights.

## Target acceptance still required

Run the Python suite on the actual >=3.51.3 linked build and Darwin ARM64. Exercise real service-account renewal, bootstrap/protections, typed reads, prepared publication/readback, a simulated lost response without duplicate send, IAM denial and actual Drive staging. Confirm optional scopes, triggers and `/exec` redirect/body handling. Do not use real exfiltration endpoints or patron records in adversarial validation.

Validate durable-storage behavior under process termination and power/fault injection separately. Existing local tests inject exceptions and reopen files; they do not certify power-failure semantics of the user's SSD/filesystem. Verify snapshots against an independently pinned key and authorized encrypted evidence storage. No old authority is promoted just because an archive verifies.

If same-resource safety cannot be established, the current publisher holds. Automatic cutover to a pre-provisioned replacement workbook, preserving old draft lineage, is not implemented as a released operation. This is an explicit conformance gap, not a hidden unsafe reuse path.
