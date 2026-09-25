# DDL enforcement manifest — schema 0.4.0

The SQL file is the exact normative fresh-database declaration. Ordinary tables are STRICT; FTS5 tables are virtual and are not declared STRICT. All ordinary business relationships are tenant-qualified; the singleton ledger row pins one tenant per file. Every connection must enable foreign keys and recursive triggers. The broker is the only permitted writer. The declaration is not an idempotent installer or a migration over an existing independent lab database. [S01, S02]

SQL constraints cover stored types, selected enums/byte limits, primary/unique identity, declared foreign keys, selected generation/revision changes, immutable-table UPDATE/DELETE rejection, and deferred existence of version/outcome/outbox records. They do not certify JCS canonicality, signatures, calendar-valid timestamps, all type-specific row completeness, artifact existence, query latency, correct state transitions, complete audit-event counts, authentic bases or business permissions. These are explicit broker/release predicates.

`INSERT OR REPLACE` is forbidden. With recursive triggers enabled, the append-only guards reject replacement of existing immutable rows; the validation report probes this. Disabling triggers/constraints or directly writing from privileged arbitrary SQL is outside the broker model. Hash chains do not protect against an administrator replacing every trusted copy and signing key.

Canonical change protocol: one admitted operation receives one ordered audit transaction; all changed entities receive one version increment and one immutable full aggregate snapshot each. Snapshots include typed facet and relevant owned-child data, not just the `entities` columns. Original entity identity is never overwritten. `merged_into_id` is set only in an audited tombstone/merge, never by name similarity.

Broker checks missing from declarative SQL: exactly one correct facet per entity; referenced organizations/opportunities have the required kind; parent/plan constraints and acyclicity; actor permission and accepted artifact content; source field/guard stamps; legitimate state graph; stamp/snapshot/current-state equality; manifest-chain/event-count correctness; outbox byte accuracy; current claim token; search text freshness; visibility classification; body-size bounds and explicit terminal timestamps. Any of these failures aborts the accepting transaction rather than relying on a later repair.

No SQL trigger writes to FTS5. The broker writes canonical search documents and the two content-bearing FTS5 projections in the same accepting transaction. This avoids relying on virtual-table use from triggers under `trusted_schema=OFF`; it also makes the missing-index-write fault an explicit acceptance test rather than an implicit guarantee of this DDL. [S05–S07]

The table inventory below is generated from the delivered DDL. PK position and nullability are SQLite metadata, not a replacement for the CHECKs and deferred references in the SQL. No fixture values are production seeds.

## ledger_state

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `singleton` | INTEGER | False | 1 |
| `tenant_id` | TEXT | True | 0 |
| `ledger_id` | TEXT | True | 0 |
| `schema_version` | INTEGER | True | 0 |
| `authority_epoch` | INTEGER | True | 0 |
| `commit_seq` | INTEGER | True | 0 |
| `head_digest` | TEXT | True | 0 |
| `search_generation` | INTEGER | True | 0 |
| `mode` | TEXT | True | 0 |
| `created_at` | TEXT | True | 0 |


## actors

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `actor_id` | TEXT | True | 2 |
| `display_name` | TEXT | True | 0 |
| `actor_kind` | TEXT | True | 0 |
| `disabled` | INTEGER | True | 0 |


## audit_transactions

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `commit_seq` | INTEGER | True | 2 |
| `operation_id` | TEXT | True | 0 |
| `authority_epoch` | INTEGER | True | 0 |
| `actor_id` | TEXT | True | 0 |
| `event_count` | INTEGER | True | 0 |
| `previous_digest` | TEXT | True | 0 |
| `transaction_digest` | TEXT | True | 0 |
| `manifest_jcs` | BLOB | True | 0 |
| `recorded_at` | TEXT | True | 0 |


## operation_outcomes

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `operation_id` | TEXT | True | 2 |
| `semantic_digest` | TEXT | True | 0 |
| `actor_id` | TEXT | True | 0 |
| `command_type` | TEXT | True | 0 |
| `disposition` | TEXT | True | 0 |
| `commit_seq` | INTEGER | True | 0 |
| `outcome_jcs` | BLOB | True | 0 |
| `recorded_at` | TEXT | True | 0 |


## entities

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `entity_id` | TEXT | True | 2 |
| `entity_kind` | TEXT | True | 0 |
| `display_name` | TEXT | True | 0 |
| `status` | TEXT | True | 0 |
| `note` | TEXT | False | 0 |
| `next_action` | TEXT | False | 0 |
| `entity_rev` | INTEGER | True | 0 |
| `last_commit_seq` | INTEGER | True | 0 |
| `mutation_epoch` | INTEGER | True | 0 |
| `state_digest` | TEXT | True | 0 |
| `created_at` | TEXT | True | 0 |
| `updated_at` | TEXT | True | 0 |
| `deleted_at` | TEXT | False | 0 |
| `merged_into_id` | TEXT | False | 0 |
| `updated_by` | TEXT | True | 0 |


## entity_versions

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `entity_id` | TEXT | True | 2 |
| `entity_rev` | INTEGER | True | 3 |
| `commit_seq` | INTEGER | True | 0 |
| `state_digest` | TEXT | True | 0 |
| `state_jcs` | BLOB | True | 0 |
| `recorded_at` | TEXT | True | 0 |


## field_revisions

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `entity_id` | TEXT | True | 2 |
| `field_name` | TEXT | True | 3 |
| `field_rev` | INTEGER | True | 0 |


## relation_guards

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `entity_id` | TEXT | True | 2 |
| `guard_name` | TEXT | True | 3 |
| `guard_rev` | INTEGER | True | 0 |
| `commit_seq` | INTEGER | True | 0 |


## campaigns

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `campaign_id` | TEXT | True | 2 |
| `entity_kind` | TEXT | True | 0 |
| `slug` | TEXT | True | 0 |
| `objective` | TEXT | False | 0 |
| `lead_actor_id` | TEXT | False | 0 |


## campaign_memberships

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `campaign_id` | TEXT | True | 2 |
| `entity_id` | TEXT | True | 3 |
| `is_primary` | INTEGER | True | 0 |
| `joined_commit_seq` | INTEGER | True | 0 |


## projects

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `project_id` | TEXT | True | 2 |
| `entity_kind` | TEXT | True | 0 |
| `slug` | TEXT | True | 0 |
| `lead_actor_id` | TEXT | False | 0 |
| `lead_model` | TEXT | False | 0 |
| `active_plan_version` | INTEGER | True | 0 |
| `dropzone_drive_id` | TEXT | False | 0 |
| `dropzone_path_hint` | TEXT | False | 0 |
| `receipt_artifact_id` | TEXT | False | 0 |


## work_items

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `work_item_id` | TEXT | True | 2 |
| `entity_kind` | TEXT | True | 0 |
| `project_id` | TEXT | True | 0 |
| `parent_work_item_id` | TEXT | False | 0 |
| `plan_version` | INTEGER | True | 0 |
| `stage_ordinal` | INTEGER | False | 0 |
| `required` | INTEGER | True | 0 |
| `assigned_actor_id` | TEXT | False | 0 |
| `acceptance_ref` | TEXT | False | 0 |
| `result_artifact_id` | TEXT | False | 0 |
| `due_at` | TEXT | False | 0 |


## patrons

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `patron_id` | TEXT | True | 2 |
| `entity_kind` | TEXT | True | 0 |
| `organization_id` | TEXT | False | 0 |
| `primary_channel_id` | TEXT | False | 0 |
| `patron_type` | TEXT | False | 0 |
| `funding_band` | TEXT | False | 0 |
| `funding_currency` | TEXT | False | 0 |
| `active_cipher_motif` | TEXT | False | 0 |
| `motif_source_artifact_id` | TEXT | False | 0 |


## commercial_records

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `commercial_id` | TEXT | True | 2 |
| `entity_kind` | TEXT | True | 0 |
| `project_id` | TEXT | True | 0 |
| `primary_patron_id` | TEXT | True | 0 |
| `origin_opportunity_id` | TEXT | False | 0 |
| `amount_minor` | INTEGER | False | 0 |
| `currency` | TEXT | False | 0 |
| `due_at` | TEXT | False | 0 |
| `artifact_id` | TEXT | False | 0 |


## communication_threads

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `thread_id` | TEXT | True | 2 |
| `entity_kind` | TEXT | True | 0 |
| `target_app` | TEXT | True | 0 |
| `connector_account_id` | TEXT | True | 0 |
| `external_thread_id` | TEXT | True | 0 |


## dispatch_attempts

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `dispatch_id` | TEXT | True | 2 |
| `entity_kind` | TEXT | True | 0 |
| `work_item_id` | TEXT | True | 0 |
| `thread_id` | TEXT | False | 0 |
| `actor_id` | TEXT | True | 0 |
| `attempt_no` | INTEGER | True | 0 |
| `prompt_hash` | TEXT | True | 0 |
| `target_app` | TEXT | True | 0 |
| `connector_account_id` | TEXT | True | 0 |
| `dispatched_at` | TEXT | False | 0 |
| `first_output_at` | TEXT | False | 0 |
| `finished_at` | TEXT | False | 0 |
| `latency_sec` | REAL | False | 0 |
| `output_artifact_id` | TEXT | False | 0 |
| `error_code` | TEXT | False | 0 |


## contact_channels

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `channel_id` | TEXT | True | 2 |
| `patron_id` | TEXT | True | 0 |
| `channel_kind` | TEXT | True | 0 |
| `original_value` | TEXT | True | 0 |
| `normalized_value` | TEXT | False | 0 |
| `normalizer_version` | TEXT | True | 0 |
| `extension` | TEXT | False | 0 |
| `source_region` | TEXT | False | 0 |
| `verified` | INTEGER | True | 0 |
| `source_artifact_id` | TEXT | False | 0 |
| `retired_at` | TEXT | False | 0 |


## entity_aliases

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `alias_id` | TEXT | True | 2 |
| `entity_id` | TEXT | True | 0 |
| `original_value` | TEXT | True | 0 |
| `normalized_key` | TEXT | True | 0 |
| `normalizer_version` | TEXT | True | 0 |
| `verified` | INTEGER | True | 0 |
| `source_artifact_id` | TEXT | False | 0 |
| `retired_at` | TEXT | False | 0 |


## artifacts

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `artifact_id` | TEXT | True | 2 |
| `media_type` | TEXT | True | 0 |
| `size_bytes` | INTEGER | True | 0 |
| `sha256` | TEXT | True | 0 |
| `object_ref` | TEXT | True | 0 |
| `object_version` | TEXT | False | 0 |
| `visibility` | TEXT | True | 0 |
| `verified_at` | TEXT | True | 0 |


## interactions

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `interaction_id` | TEXT | True | 2 |
| `patron_id` | TEXT | True | 0 |
| `thread_id` | TEXT | False | 0 |
| `supersedes_interaction_id` | TEXT | False | 0 |
| `record_kind` | TEXT | True | 0 |
| `subject` | TEXT | True | 0 |
| `summary` | TEXT | False | 0 |
| `approved_excerpt` | TEXT | False | 0 |
| `source_artifact_id` | TEXT | False | 0 |
| `occurred_at` | TEXT | True | 0 |
| `recorded_at` | TEXT | True | 0 |
| `commit_seq` | INTEGER | True | 0 |
| `actor_id` | TEXT | True | 0 |


## thread_chunks

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `dispatch_id` | TEXT | True | 2 |
| `chunk_index` | INTEGER | True | 3 |
| `sha256` | TEXT | True | 0 |
| `artifact_id` | TEXT | True | 0 |
| `commit_seq` | INTEGER | True | 0 |


## claims

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `resource_id` | TEXT | True | 2 |
| `claim_generation` | INTEGER | True | 0 |
| `holder_actor_id` | TEXT | False | 0 |
| `claim_operation_id` | TEXT | False | 0 |
| `claim_state` | TEXT | True | 0 |
| `authority_epoch` | INTEGER | True | 0 |
| `updated_commit_seq` | INTEGER | True | 0 |


## external_actions

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `action_id` | TEXT | True | 2 |
| `resource_id` | TEXT | True | 0 |
| `claim_generation` | INTEGER | True | 0 |
| `holder_actor_id` | TEXT | True | 0 |
| `authority_epoch` | INTEGER | True | 0 |
| `request_digest` | TEXT | True | 0 |
| `request_artifact_id` | TEXT | True | 0 |
| `state` | TEXT | True | 0 |
| `created_commit_seq` | INTEGER | True | 0 |


## audit_log

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `commit_seq` | INTEGER | True | 2 |
| `event_ordinal` | INTEGER | True | 3 |
| `event_kind` | TEXT | True | 0 |
| `entity_id` | TEXT | False | 0 |
| `prior_entity_rev` | INTEGER | False | 0 |
| `new_entity_rev` | INTEGER | False | 0 |
| `event_jcs` | BLOB | True | 0 |
| `event_digest` | TEXT | True | 0 |


## projection_resources

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `generation_id` | TEXT | True | 2 |
| `spreadsheet_id` | TEXT | True | 0 |
| `state` | TEXT | True | 0 |
| `layout_digest` | TEXT | True | 0 |
| `published_commit_seq` | INTEGER | True | 0 |
| `change_next_row` | INTEGER | True | 0 |
| `created_at` | TEXT | True | 0 |


## publication_batches

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `batch_id` | TEXT | True | 2 |
| `generation_id` | TEXT | True | 0 |
| `first_commit_seq` | INTEGER | True | 0 |
| `last_commit_seq` | INTEGER | True | 0 |
| `business_rows` | INTEGER | True | 0 |
| `payload_bytes` | INTEGER | True | 0 |
| `payload_digest` | TEXT | True | 0 |
| `payload_object_ref` | TEXT | True | 0 |
| `receipt_row` | INTEGER | True | 0 |
| `state` | TEXT | True | 0 |
| `created_at` | TEXT | True | 0 |
| `verified_at` | TEXT | False | 0 |


## sync_outbox

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `commit_seq` | INTEGER | True | 2 |
| `encoded_bytes` | INTEGER | True | 0 |
| `batch_id` | TEXT | False | 0 |
| `state` | TEXT | True | 0 |
| `created_at` | TEXT | True | 0 |


## delivery_events

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `delivery_event_seq` | INTEGER | False | 1 |
| `tenant_id` | TEXT | True | 0 |
| `batch_id` | TEXT | True | 0 |
| `attempt_id` | TEXT | True | 0 |
| `event_kind` | TEXT | True | 0 |
| `recorded_at` | TEXT | True | 0 |
| `reason_code` | TEXT | False | 0 |
| `http_status` | INTEGER | False | 0 |
| `provider_evidence_ref` | TEXT | False | 0 |


## quota_reservations

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `reservation_seq` | INTEGER | False | 1 |
| `consumer_project` | TEXT | True | 0 |
| `principal_ref` | TEXT | True | 0 |
| `quota_class` | TEXT | True | 0 |
| `attempt_id` | TEXT | True | 0 |
| `reserved_at` | TEXT | True | 0 |
| `not_before_at` | TEXT | True | 0 |
| `boot_id` | TEXT | True | 0 |
| `monotonic_ns` | INTEGER | True | 0 |


## quarantine_proposals

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `proposal_id` | TEXT | True | 2 |
| `observation_seq` | INTEGER | True | 0 |
| `source_kind` | TEXT | True | 0 |
| `source_resource_id` | TEXT | True | 0 |
| `source_generation_id` | TEXT | False | 0 |
| `source_sheet_id` | INTEGER | False | 0 |
| `source_row` | INTEGER | False | 0 |
| `source_column` | INTEGER | False | 0 |
| `target_entity_id` | TEXT | False | 0 |
| `target_field` | TEXT | False | 0 |
| `evidence_digest` | TEXT | True | 0 |
| `evidence_size` | INTEGER | True | 0 |
| `evidence_object_ref` | TEXT | True | 0 |
| `reason_code` | TEXT | True | 0 |
| `value_kind` | TEXT | True | 0 |
| `base_commit_seq` | INTEGER | False | 0 |
| `captured_at` | TEXT | True | 0 |
| `capture_operation_id` | TEXT | True | 0 |


## observation_heads

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `source_key_digest` | TEXT | True | 2 |
| `proposal_id` | TEXT | True | 0 |
| `selection_rev` | INTEGER | True | 0 |
| `observed_digest` | TEXT | True | 0 |


## proposal_resolutions

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `proposal_id` | TEXT | True | 2 |
| `operation_id` | TEXT | True | 0 |
| `decision` | TEXT | True | 0 |
| `selected_revision` | INTEGER | True | 0 |
| `actor_id` | TEXT | True | 0 |
| `reason_code` | TEXT | True | 0 |
| `resolved_at` | TEXT | True | 0 |


## capture_checkpoints

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `source_key` | TEXT | True | 2 |
| `cursor_value` | TEXT | False | 0 |
| `dirty` | INTEGER | True | 0 |
| `last_scan_at` | TEXT | False | 0 |
| `last_complete_sweep_at` | TEXT | False | 0 |


## staging_receipts

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `file_id` | TEXT | True | 2 |
| `content_digest` | TEXT | True | 3 |
| `delivery_id` | TEXT | True | 0 |
| `operation_id` | TEXT | False | 0 |
| `disposition` | TEXT | True | 0 |
| `recorded_at` | TEXT | True | 0 |


## projection_rows

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `generation_id` | TEXT | True | 2 |
| `tab_key` | TEXT | True | 3 |
| `entity_id` | TEXT | True | 4 |
| `sheet_id` | INTEGER | True | 0 |
| `row_index` | INTEGER | True | 0 |
| `projection_seq` | INTEGER | True | 0 |
| `row_digest` | TEXT | False | 0 |


## entity_search_documents

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `search_doc_id` | INTEGER | False | 1 |
| `tenant_id` | TEXT | True | 0 |
| `entity_id` | TEXT | True | 0 |
| `entity_kind` | TEXT | True | 0 |
| `display_name` | TEXT | True | 0 |
| `aliases` | TEXT | True | 0 |
| `organization_name` | TEXT | True | 0 |
| `summary` | TEXT | True | 0 |
| `next_action` | TEXT | True | 0 |
| `source_entity_rev` | INTEGER | True | 0 |
| `source_projection_seq` | INTEGER | True | 0 |
| `search_generation` | INTEGER | True | 0 |


## interaction_search_documents

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `search_doc_id` | INTEGER | False | 1 |
| `tenant_id` | TEXT | True | 0 |
| `interaction_id` | TEXT | True | 0 |
| `patron_id` | TEXT | True | 0 |
| `communication_thread_id` | TEXT | False | 0 |
| `subject` | TEXT | True | 0 |
| `participants` | TEXT | True | 0 |
| `summary` | TEXT | True | 0 |
| `excerpt` | TEXT | True | 0 |
| `occurred_at` | TEXT | True | 0 |
| `recorded_at` | TEXT | True | 0 |
| `source_commit_seq` | INTEGER | True | 0 |
| `search_generation` | INTEGER | True | 0 |


## name_grams

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `normalizer_version` | TEXT | True | 2 |
| `gram` | TEXT | True | 3 |
| `search_doc_id` | INTEGER | True | 4 |


## legacy_identifiers

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `identifier_scheme` | TEXT | True | 2 |
| `original_value` | TEXT | True | 3 |
| `entity_id` | TEXT | True | 0 |


## snapshot_manifests

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `snapshot_id` | TEXT | True | 2 |
| `terminal_commit_seq` | INTEGER | True | 0 |
| `manifest_digest` | TEXT | True | 0 |
| `object_ref` | TEXT | True | 0 |
| `signer_key_id` | TEXT | True | 0 |
| `ed25519_signature` | BLOB | True | 0 |
| `verified_at` | TEXT | True | 0 |


## schema_migrations

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `version` | INTEGER | False | 1 |
| `ddl_digest` | TEXT | True | 0 |
| `applied_at` | TEXT | True | 0 |
| `previous_snapshot_id` | TEXT | False | 0 |
| `evidence_ref` | TEXT | True | 0 |


## telemetry_contracts

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `contract_id` | TEXT | True | 2 |
| `producer_digest` | TEXT | True | 0 |
| `contract_jcs` | BLOB | True | 0 |
| `accepted_commit_seq` | INTEGER | True | 0 |


## telemetry_events

| Column | Storage type | NOT NULL | PK position |
|---|---|---|---|
| `tenant_id` | TEXT | True | 1 |
| `sample_id` | TEXT | True | 2 |
| `contract_id` | TEXT | True | 0 |
| `source_id` | TEXT | True | 0 |
| `run_id` | TEXT | True | 0 |
| `source_seq` | INTEGER | True | 0 |
| `observed_at` | TEXT | True | 0 |
| `received_at` | TEXT | True | 0 |
| `sample_jcs` | BLOB | True | 0 |
| `sample_digest` | TEXT | True | 0 |
| `supersedes_sample_id` | TEXT | False | 0 |
| `commit_seq` | INTEGER | True | 0 |

## entity_fts

`tenant_id`, `entity_id`, `entity_kind`, `display_name`, `aliases`, `organization_name`, `summary`, `next_action`, `source_entity_rev`, `source_projection_seq`, `search_generation`. Ordinary content-bearing FTS5; rowid is the corresponding stable local search-document integer, not a ULID.

## interaction_fts

`tenant_id`, `interaction_id`, `patron_id`, `communication_thread_id`, `subject`, `participants`, `summary`, `excerpt`, `occurred_at`, `recorded_at`, `source_commit_seq`, `search_generation`. Ordinary content-bearing FTS5; rowid is the corresponding stable local search-document integer, not a ULID.
