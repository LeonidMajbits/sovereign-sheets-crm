-- Sovereign Google Sheets CRM | schema release 0.4.0 | 2026-09-23
-- DECLARATIVE SCHEMA ONLY. No CRM engine, migrations, seeds, credentials or webhook.
-- Fresh empty database only. Do not run against an existing authority.
-- Runtime baseline: SQLite >=3.51.3, FTS5 + JSON functions + FK/trigger support.
-- DDL syntax inspection may use an older compatible in-memory interpreter;
-- that does NOT certify its WAL build for production.
-- Connection contract, not set here: foreign_keys=ON, recursive_triggers=ON,
-- trusted_schema=OFF (no FTS-writing triggers are declared), synchronous=FULL,
-- journal_mode=WAL on verified local storage; loadable extensions disabled.
-- Same-transaction domain/audit/search/outbox consistency is partly broker-owned:
-- see specification section 3 and schema/DDL_Enforcement_Manifest.md.
-- All relation keys are tenant qualified. One ledger_state row = one tenant/file.
-- JCS bytes must be verified by the protocol validator; SQL json_valid is weaker.
-- Do not use INSERT OR REPLACE on canonical/immutable relations.

CREATE TABLE ledger_state (
  singleton INTEGER PRIMARY KEY CHECK (singleton=1),
  tenant_id TEXT NOT NULL CHECK (length(tenant_id)=26 AND substr(tenant_id,1,1) BETWEEN '0' AND '7' AND tenant_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  ledger_id TEXT NOT NULL CHECK (length(ledger_id)=26 AND substr(ledger_id,1,1) BETWEEN '0' AND '7' AND ledger_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  schema_version INTEGER NOT NULL CHECK (schema_version=4),
  authority_epoch INTEGER NOT NULL CHECK (authority_epoch>0),
  commit_seq INTEGER NOT NULL CHECK (commit_seq>=0),
  head_digest TEXT NOT NULL CHECK (length(head_digest)=64 AND head_digest NOT GLOB '*[^0123456789abcdef]*'),
  search_generation INTEGER NOT NULL CHECK (search_generation>0),
  mode TEXT NOT NULL CHECK (mode IN ('NORMAL','MAINTENANCE','RECOVERY_HOLD')),
  created_at TEXT NOT NULL,
  UNIQUE (tenant_id),
  UNIQUE (ledger_id)
) STRICT;

CREATE TABLE actors (
  tenant_id TEXT NOT NULL,
  actor_id TEXT NOT NULL CHECK (length(actor_id)=26 AND substr(actor_id,1,1) BETWEEN '0' AND '7' AND actor_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  display_name TEXT NOT NULL CHECK (length(CAST(display_name AS BLOB)) <= 1024 AND instr(display_name,char(0))=0),
  actor_kind TEXT NOT NULL CHECK (actor_kind IN ('human','agent','service')),
  disabled INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0,1)),
  PRIMARY KEY (tenant_id, actor_id),
  FOREIGN KEY (tenant_id) REFERENCES ledger_state (tenant_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE audit_transactions (
  tenant_id TEXT NOT NULL,
  commit_seq INTEGER NOT NULL CHECK (commit_seq>0),
  operation_id TEXT NOT NULL CHECK (length(operation_id)=26 AND substr(operation_id,1,1) BETWEEN '0' AND '7' AND operation_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  authority_epoch INTEGER NOT NULL CHECK (authority_epoch>0),
  actor_id TEXT NOT NULL,
  event_count INTEGER NOT NULL CHECK (event_count BETWEEN 1 AND 128),
  previous_digest TEXT NOT NULL CHECK (length(previous_digest)=64 AND previous_digest NOT GLOB '*[^0123456789abcdef]*'),
  transaction_digest TEXT NOT NULL CHECK (length(transaction_digest)=64 AND transaction_digest NOT GLOB '*[^0123456789abcdef]*'),
  manifest_jcs BLOB NOT NULL CHECK (length(manifest_jcs)<=24576 AND json_valid(CAST(manifest_jcs AS TEXT))),
  recorded_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, commit_seq),
  UNIQUE (tenant_id, operation_id),
  FOREIGN KEY (tenant_id) REFERENCES ledger_state (tenant_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, actor_id) REFERENCES actors (tenant_id, actor_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, operation_id) REFERENCES operation_outcomes (tenant_id, operation_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, commit_seq) REFERENCES sync_outbox (tenant_id, commit_seq) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE operation_outcomes (
  tenant_id TEXT NOT NULL,
  operation_id TEXT NOT NULL CHECK (length(operation_id)=26 AND substr(operation_id,1,1) BETWEEN '0' AND '7' AND operation_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  semantic_digest TEXT NOT NULL CHECK (length(semantic_digest)=64 AND semantic_digest NOT GLOB '*[^0123456789abcdef]*'),
  actor_id TEXT NOT NULL,
  command_type TEXT NOT NULL CHECK (length(CAST(command_type AS BLOB)) <= 80 AND instr(command_type,char(0))=0),
  disposition TEXT NOT NULL CHECK (disposition IN ('COMMITTED','SATISFIED_NO_CHANGE','CONFLICT','REJECTED','CAPTURED_UNBASED','RESOLVED')),
  commit_seq INTEGER NOT NULL CHECK (commit_seq>0),
  outcome_jcs BLOB NOT NULL CHECK (length(outcome_jcs)<=24576 AND json_valid(CAST(outcome_jcs AS TEXT))),
  recorded_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, operation_id),
  UNIQUE (tenant_id, commit_seq),
  FOREIGN KEY (tenant_id, actor_id) REFERENCES actors (tenant_id, actor_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, commit_seq) REFERENCES audit_transactions (tenant_id, commit_seq) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE entities (
  tenant_id TEXT NOT NULL,
  entity_id TEXT NOT NULL CHECK (length(entity_id)=26 AND substr(entity_id,1,1) BETWEEN '0' AND '7' AND entity_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  entity_kind TEXT NOT NULL,
  display_name TEXT NOT NULL CHECK (length(CAST(display_name AS BLOB)) <= 1024 AND instr(display_name,char(0))=0),
  status TEXT NOT NULL,
  note TEXT  CHECK (length(CAST(note AS BLOB)) <= 2048 AND instr(note,char(0))=0),
  next_action TEXT  CHECK (length(CAST(next_action AS BLOB)) <= 1024 AND instr(next_action,char(0))=0),
  entity_rev INTEGER NOT NULL CHECK (entity_rev>0),
  last_commit_seq INTEGER NOT NULL CHECK (last_commit_seq>0),
  mutation_epoch INTEGER NOT NULL CHECK (mutation_epoch>0),
  state_digest TEXT NOT NULL CHECK (length(state_digest)=64 AND state_digest NOT GLOB '*[^0123456789abcdef]*'),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT,
  merged_into_id TEXT,
  updated_by TEXT NOT NULL,
  PRIMARY KEY (tenant_id, entity_id),
  CHECK (merged_into_id IS NULL OR (merged_into_id<>entity_id AND deleted_at IS NOT NULL)),
  FOREIGN KEY (tenant_id, merged_into_id) REFERENCES entities (tenant_id, entity_id) DEFERRABLE INITIALLY DEFERRED,
  UNIQUE (tenant_id, entity_id, entity_kind),
  CHECK ((entity_kind='person' AND status IN ('lead','engaged','closed')) OR (entity_kind='organization' AND status IN ('lead','engaged','closed')) OR (entity_kind='campaign' AND status IN ('active','completed','shelved')) OR (entity_kind='project' AND status IN ('active','completed','shelved')) OR (entity_kind='stage' AND status IN ('queued','running','blocked','completed','cancelled')) OR (entity_kind='ticket' AND status IN ('queued','running','blocked','completed','cancelled')) OR (entity_kind='opportunity' AND status IN ('lead','qualified','proposed','won','lost')) OR (entity_kind='contract' AND status IN ('draft','signed','fulfilled','terminated')) OR (entity_kind='thread' AND status IN ('open','closed')) OR (entity_kind='dispatch' AND status IN ('queued','cooking','harvested','error','cancelled','unknown'))),
  FOREIGN KEY (tenant_id) REFERENCES ledger_state (tenant_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, updated_by) REFERENCES actors (tenant_id, actor_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, last_commit_seq) REFERENCES audit_transactions (tenant_id, commit_seq) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, entity_id, entity_rev) REFERENCES entity_versions (tenant_id, entity_id, entity_rev) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE INDEX entities_kind_status ON entities (tenant_id, entity_kind, status, entity_id) WHERE deleted_at IS NULL;

CREATE TABLE entity_versions (
  tenant_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  entity_rev INTEGER NOT NULL CHECK (entity_rev>0),
  commit_seq INTEGER NOT NULL CHECK (commit_seq>0),
  state_digest TEXT NOT NULL CHECK (length(state_digest)=64 AND state_digest NOT GLOB '*[^0123456789abcdef]*'),
  state_jcs BLOB NOT NULL CHECK (length(state_jcs)<=24576 AND json_valid(CAST(state_jcs AS TEXT))),
  recorded_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, entity_id, entity_rev),
  UNIQUE (tenant_id, entity_id, commit_seq),
  FOREIGN KEY (tenant_id, entity_id) REFERENCES entities (tenant_id, entity_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, commit_seq) REFERENCES audit_transactions (tenant_id, commit_seq) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE field_revisions (
  tenant_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  field_name TEXT NOT NULL CHECK (length(CAST(field_name AS BLOB)) <= 128 AND instr(field_name,char(0))=0),
  field_rev INTEGER NOT NULL CHECK (field_rev>0),
  PRIMARY KEY (tenant_id, entity_id, field_name),
  FOREIGN KEY (tenant_id, entity_id, field_rev) REFERENCES entity_versions (tenant_id, entity_id, entity_rev) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE relation_guards (
  tenant_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  guard_name TEXT NOT NULL CHECK (length(CAST(guard_name AS BLOB)) <= 128 AND instr(guard_name,char(0))=0),
  guard_rev INTEGER NOT NULL CHECK (guard_rev>0),
  commit_seq INTEGER NOT NULL CHECK (commit_seq>0),
  PRIMARY KEY (tenant_id, entity_id, guard_name),
  FOREIGN KEY (tenant_id, entity_id) REFERENCES entities (tenant_id, entity_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, commit_seq) REFERENCES audit_transactions (tenant_id, commit_seq) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE campaigns (
  tenant_id TEXT NOT NULL,
  campaign_id TEXT NOT NULL,
  entity_kind TEXT NOT NULL CHECK (entity_kind IN ('campaign')),
  slug TEXT NOT NULL CHECK (length(CAST(slug AS BLOB)) <= 128 AND instr(slug,char(0))=0),
  objective TEXT  CHECK (length(CAST(objective AS BLOB)) <= 2048 AND instr(objective,char(0))=0),
  lead_actor_id TEXT,
  UNIQUE (tenant_id, slug),
  FOREIGN KEY (tenant_id, lead_actor_id) REFERENCES actors (tenant_id, actor_id) DEFERRABLE INITIALLY DEFERRED,
  PRIMARY KEY (tenant_id, campaign_id),
  FOREIGN KEY (tenant_id, campaign_id, entity_kind) REFERENCES entities (tenant_id, entity_id, entity_kind) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE campaign_memberships (
  tenant_id TEXT NOT NULL,
  campaign_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  is_primary INTEGER NOT NULL CHECK (is_primary IN (0,1)),
  joined_commit_seq INTEGER NOT NULL,
  PRIMARY KEY (tenant_id, campaign_id, entity_id),
  FOREIGN KEY (tenant_id, campaign_id) REFERENCES campaigns (tenant_id, campaign_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, entity_id) REFERENCES entities (tenant_id, entity_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, joined_commit_seq) REFERENCES audit_transactions (tenant_id, commit_seq) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE UNIQUE INDEX membership_primary ON campaign_memberships (tenant_id, entity_id) WHERE is_primary=1;

CREATE INDEX membership_entity ON campaign_memberships (tenant_id, entity_id, campaign_id);

CREATE TABLE projects (
  tenant_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  entity_kind TEXT NOT NULL CHECK (entity_kind IN ('project')),
  slug TEXT NOT NULL CHECK (length(CAST(slug AS BLOB)) <= 128 AND instr(slug,char(0))=0),
  lead_actor_id TEXT,
  lead_model TEXT  CHECK (length(CAST(lead_model AS BLOB)) <= 128 AND instr(lead_model,char(0))=0),
  active_plan_version INTEGER NOT NULL DEFAULT 0 CHECK (active_plan_version>=0),
  dropzone_drive_id TEXT,
  dropzone_path_hint TEXT  CHECK (length(CAST(dropzone_path_hint AS BLOB)) <= 4096 AND instr(dropzone_path_hint,char(0))=0),
  receipt_artifact_id TEXT,
  UNIQUE (tenant_id, slug),
  FOREIGN KEY (tenant_id, lead_actor_id) REFERENCES actors (tenant_id, actor_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, receipt_artifact_id) REFERENCES artifacts (tenant_id, artifact_id) DEFERRABLE INITIALLY DEFERRED,
  PRIMARY KEY (tenant_id, project_id),
  FOREIGN KEY (tenant_id, project_id, entity_kind) REFERENCES entities (tenant_id, entity_id, entity_kind) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE work_items (
  tenant_id TEXT NOT NULL,
  work_item_id TEXT NOT NULL,
  entity_kind TEXT NOT NULL CHECK (entity_kind IN ('stage','ticket')),
  project_id TEXT NOT NULL,
  parent_work_item_id TEXT,
  plan_version INTEGER NOT NULL CHECK (plan_version>0),
  stage_ordinal INTEGER CHECK (stage_ordinal>0),
  required INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0,1)),
  assigned_actor_id TEXT,
  acceptance_ref TEXT  CHECK (length(CAST(acceptance_ref AS BLOB)) <= 2048 AND instr(acceptance_ref,char(0))=0),
  result_artifact_id TEXT,
  due_at TEXT,
  CHECK ((entity_kind='stage' AND stage_ordinal IS NOT NULL AND parent_work_item_id IS NULL) OR (entity_kind='ticket' AND stage_ordinal IS NULL)),
  CHECK (parent_work_item_id IS NULL OR parent_work_item_id<>work_item_id),
  UNIQUE (tenant_id, project_id, plan_version, stage_ordinal),
  UNIQUE (tenant_id, work_item_id, project_id),
  FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, project_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, parent_work_item_id, project_id) REFERENCES work_items (tenant_id, work_item_id, project_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, assigned_actor_id) REFERENCES actors (tenant_id, actor_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, result_artifact_id) REFERENCES artifacts (tenant_id, artifact_id) DEFERRABLE INITIALLY DEFERRED,
  PRIMARY KEY (tenant_id, work_item_id),
  FOREIGN KEY (tenant_id, work_item_id, entity_kind) REFERENCES entities (tenant_id, entity_id, entity_kind) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE INDEX work_items_project ON work_items (tenant_id, project_id, plan_version, work_item_id);

CREATE TABLE patrons (
  tenant_id TEXT NOT NULL,
  patron_id TEXT NOT NULL,
  entity_kind TEXT NOT NULL CHECK (entity_kind IN ('person','organization')),
  organization_id TEXT,
  primary_channel_id TEXT,
  patron_type TEXT CHECK (patron_type IN ('angel','institutional','individual','business','other')),
  funding_band TEXT  CHECK (length(CAST(funding_band AS BLOB)) <= 128 AND instr(funding_band,char(0))=0),
  funding_currency TEXT CHECK (length(funding_currency)=3 AND funding_currency NOT GLOB '*[^A-Z]*'),
  active_cipher_motif TEXT  CHECK (length(CAST(active_cipher_motif AS BLOB)) <= 1024 AND instr(active_cipher_motif,char(0))=0),
  motif_source_artifact_id TEXT,
  CHECK (organization_id IS NULL OR (entity_kind='person' AND organization_id<>patron_id)),
  FOREIGN KEY (tenant_id, organization_id) REFERENCES patrons (tenant_id, patron_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, primary_channel_id, patron_id) REFERENCES contact_channels (tenant_id, channel_id, patron_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, motif_source_artifact_id) REFERENCES artifacts (tenant_id, artifact_id) DEFERRABLE INITIALLY DEFERRED,
  PRIMARY KEY (tenant_id, patron_id),
  FOREIGN KEY (tenant_id, patron_id, entity_kind) REFERENCES entities (tenant_id, entity_id, entity_kind) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE INDEX patrons_org ON patrons (tenant_id, organization_id, patron_id);

CREATE TABLE commercial_records (
  tenant_id TEXT NOT NULL,
  commercial_id TEXT NOT NULL,
  entity_kind TEXT NOT NULL CHECK (entity_kind IN ('opportunity','contract')),
  project_id TEXT NOT NULL,
  primary_patron_id TEXT NOT NULL,
  origin_opportunity_id TEXT,
  amount_minor INTEGER CHECK (amount_minor>=0),
  currency TEXT CHECK (length(currency)=3 AND currency NOT GLOB '*[^A-Z]*'),
  due_at TEXT,
  artifact_id TEXT,
  CHECK (amount_minor IS NULL OR currency IS NOT NULL),
  CHECK (origin_opportunity_id IS NULL OR (entity_kind='contract' AND origin_opportunity_id<>commercial_id)),
  FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, project_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, primary_patron_id) REFERENCES patrons (tenant_id, patron_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, origin_opportunity_id) REFERENCES commercial_records (tenant_id, commercial_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, artifact_id) REFERENCES artifacts (tenant_id, artifact_id) DEFERRABLE INITIALLY DEFERRED,
  PRIMARY KEY (tenant_id, commercial_id),
  FOREIGN KEY (tenant_id, commercial_id, entity_kind) REFERENCES entities (tenant_id, entity_id, entity_kind) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE INDEX commercial_project ON commercial_records (tenant_id, project_id, due_at, commercial_id);

CREATE TABLE communication_threads (
  tenant_id TEXT NOT NULL,
  thread_id TEXT NOT NULL,
  entity_kind TEXT NOT NULL CHECK (entity_kind IN ('thread')),
  target_app TEXT NOT NULL CHECK (length(CAST(target_app AS BLOB)) <= 80 AND instr(target_app,char(0))=0),
  connector_account_id TEXT NOT NULL CHECK (length(CAST(connector_account_id AS BLOB)) <= 256 AND instr(connector_account_id,char(0))=0),
  external_thread_id TEXT NOT NULL CHECK (length(CAST(external_thread_id AS BLOB)) <= 512 AND instr(external_thread_id,char(0))=0),
  UNIQUE (tenant_id, target_app, connector_account_id, external_thread_id),
  PRIMARY KEY (tenant_id, thread_id),
  FOREIGN KEY (tenant_id, thread_id, entity_kind) REFERENCES entities (tenant_id, entity_id, entity_kind) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE dispatch_attempts (
  tenant_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  entity_kind TEXT NOT NULL CHECK (entity_kind IN ('dispatch')),
  work_item_id TEXT NOT NULL,
  thread_id TEXT,
  actor_id TEXT NOT NULL,
  attempt_no INTEGER NOT NULL CHECK (attempt_no>0),
  prompt_hash TEXT NOT NULL CHECK (length(prompt_hash)=64 AND prompt_hash NOT GLOB '*[^0123456789abcdef]*'),
  target_app TEXT NOT NULL CHECK (length(CAST(target_app AS BLOB)) <= 80 AND instr(target_app,char(0))=0),
  connector_account_id TEXT NOT NULL CHECK (length(CAST(connector_account_id AS BLOB)) <= 256 AND instr(connector_account_id,char(0))=0),
  dispatched_at TEXT,
  first_output_at TEXT,
  finished_at TEXT,
  latency_sec REAL CHECK (latency_sec>=0 AND latency_sec<1.0e12),
  output_artifact_id TEXT,
  error_code TEXT  CHECK (length(CAST(error_code AS BLOB)) <= 80 AND instr(error_code,char(0))=0),
  UNIQUE (tenant_id, work_item_id, attempt_no),
  FOREIGN KEY (tenant_id, work_item_id) REFERENCES work_items (tenant_id, work_item_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, thread_id) REFERENCES communication_threads (tenant_id, thread_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, actor_id) REFERENCES actors (tenant_id, actor_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, output_artifact_id) REFERENCES artifacts (tenant_id, artifact_id) DEFERRABLE INITIALLY DEFERRED,
  PRIMARY KEY (tenant_id, dispatch_id),
  FOREIGN KEY (tenant_id, dispatch_id, entity_kind) REFERENCES entities (tenant_id, entity_id, entity_kind) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE contact_channels (
  tenant_id TEXT NOT NULL,
  channel_id TEXT NOT NULL CHECK (length(channel_id)=26 AND substr(channel_id,1,1) BETWEEN '0' AND '7' AND channel_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  patron_id TEXT NOT NULL,
  channel_kind TEXT NOT NULL CHECK (channel_kind IN ('email','phone','domain','other')),
  original_value TEXT NOT NULL CHECK (length(CAST(original_value AS BLOB)) <= 1024 AND instr(original_value,char(0))=0),
  normalized_value TEXT  CHECK (length(CAST(normalized_value AS BLOB)) <= 1024 AND instr(normalized_value,char(0))=0),
  normalizer_version TEXT NOT NULL,
  extension TEXT  CHECK (length(CAST(extension AS BLOB)) <= 32 AND instr(extension,char(0))=0),
  source_region TEXT,
  verified INTEGER NOT NULL CHECK (verified IN (0,1)),
  source_artifact_id TEXT,
  retired_at TEXT,
  PRIMARY KEY (tenant_id, channel_id),
  UNIQUE (tenant_id, channel_id, patron_id),
  FOREIGN KEY (tenant_id, patron_id) REFERENCES patrons (tenant_id, patron_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, source_artifact_id) REFERENCES artifacts (tenant_id, artifact_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE INDEX channels_match ON contact_channels (tenant_id, channel_kind, normalizer_version, normalized_value, extension);

CREATE TABLE entity_aliases (
  tenant_id TEXT NOT NULL,
  alias_id TEXT NOT NULL CHECK (length(alias_id)=26 AND substr(alias_id,1,1) BETWEEN '0' AND '7' AND alias_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  entity_id TEXT NOT NULL,
  original_value TEXT NOT NULL CHECK (length(CAST(original_value AS BLOB)) <= 1024 AND instr(original_value,char(0))=0),
  normalized_key TEXT NOT NULL CHECK (length(CAST(normalized_key AS BLOB)) <= 1024 AND instr(normalized_key,char(0))=0),
  normalizer_version TEXT NOT NULL,
  verified INTEGER NOT NULL CHECK (verified IN (0,1)),
  source_artifact_id TEXT,
  retired_at TEXT,
  PRIMARY KEY (tenant_id, alias_id),
  FOREIGN KEY (tenant_id, entity_id) REFERENCES entities (tenant_id, entity_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, source_artifact_id) REFERENCES artifacts (tenant_id, artifact_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE INDEX alias_match ON entity_aliases (tenant_id, normalizer_version, normalized_key, entity_id);

CREATE TABLE artifacts (
  tenant_id TEXT NOT NULL,
  artifact_id TEXT NOT NULL CHECK (length(artifact_id)=26 AND substr(artifact_id,1,1) BETWEEN '0' AND '7' AND artifact_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  media_type TEXT NOT NULL CHECK (length(CAST(media_type AS BLOB)) <= 128 AND instr(media_type,char(0))=0),
  size_bytes INTEGER NOT NULL CHECK (size_bytes>=0),
  sha256 TEXT NOT NULL CHECK (length(sha256)=64 AND sha256 NOT GLOB '*[^0123456789abcdef]*'),
  object_ref TEXT NOT NULL CHECK (length(CAST(object_ref AS BLOB)) <= 4096 AND instr(object_ref,char(0))=0),
  object_version TEXT  CHECK (length(CAST(object_version AS BLOB)) <= 512 AND instr(object_version,char(0))=0),
  visibility TEXT NOT NULL CHECK (visibility IN ('local_only','workbook_audience')),
  verified_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, artifact_id),
  FOREIGN KEY (tenant_id) REFERENCES ledger_state (tenant_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE interactions (
  tenant_id TEXT NOT NULL,
  interaction_id TEXT NOT NULL CHECK (length(interaction_id)=26 AND substr(interaction_id,1,1) BETWEEN '0' AND '7' AND interaction_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  patron_id TEXT NOT NULL,
  thread_id TEXT,
  supersedes_interaction_id TEXT,
  record_kind TEXT NOT NULL CHECK (record_kind IN ('touchpoint','correction','retraction')),
  subject TEXT NOT NULL CHECK (length(CAST(subject AS BLOB)) <= 512 AND instr(subject,char(0))=0),
  summary TEXT  CHECK (length(CAST(summary AS BLOB)) <= 2048 AND instr(summary,char(0))=0),
  approved_excerpt TEXT  CHECK (length(CAST(approved_excerpt AS BLOB)) <= 4096 AND instr(approved_excerpt,char(0))=0),
  source_artifact_id TEXT,
  occurred_at TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  commit_seq INTEGER NOT NULL,
  actor_id TEXT NOT NULL,
  CHECK ((record_kind='touchpoint' AND supersedes_interaction_id IS NULL) OR (record_kind IN ('correction','retraction') AND supersedes_interaction_id IS NOT NULL)),
  CHECK (supersedes_interaction_id IS NULL OR supersedes_interaction_id<>interaction_id),
  PRIMARY KEY (tenant_id, interaction_id),
  UNIQUE (tenant_id, interaction_id, patron_id),
  FOREIGN KEY (tenant_id, patron_id) REFERENCES patrons (tenant_id, patron_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, thread_id) REFERENCES communication_threads (tenant_id, thread_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, supersedes_interaction_id, patron_id) REFERENCES interactions (tenant_id, interaction_id, patron_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, source_artifact_id) REFERENCES artifacts (tenant_id, artifact_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, commit_seq) REFERENCES audit_transactions (tenant_id, commit_seq) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, actor_id) REFERENCES actors (tenant_id, actor_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE UNIQUE INDEX interaction_supersession ON interactions (tenant_id, supersedes_interaction_id) WHERE supersedes_interaction_id IS NOT NULL;

CREATE INDEX interaction_timeline ON interactions (tenant_id, patron_id, occurred_at, interaction_id);

CREATE TABLE thread_chunks (
  tenant_id TEXT NOT NULL,
  dispatch_id TEXT NOT NULL,
  chunk_index INTEGER NOT NULL CHECK (chunk_index>=0),
  sha256 TEXT NOT NULL CHECK (length(sha256)=64 AND sha256 NOT GLOB '*[^0123456789abcdef]*'),
  artifact_id TEXT NOT NULL,
  commit_seq INTEGER NOT NULL,
  PRIMARY KEY (tenant_id, dispatch_id, chunk_index),
  FOREIGN KEY (tenant_id, dispatch_id) REFERENCES dispatch_attempts (tenant_id, dispatch_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, artifact_id) REFERENCES artifacts (tenant_id, artifact_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, commit_seq) REFERENCES audit_transactions (tenant_id, commit_seq) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE claims (
  tenant_id TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  claim_generation INTEGER NOT NULL CHECK (claim_generation>=0),
  holder_actor_id TEXT,
  claim_operation_id TEXT,
  claim_state TEXT NOT NULL CHECK (claim_state IN ('UNCLAIMED','HELD','RECOVERY_HOLD')),
  authority_epoch INTEGER NOT NULL CHECK (authority_epoch>0),
  updated_commit_seq INTEGER NOT NULL,
  CHECK ((claim_state='UNCLAIMED' AND holder_actor_id IS NULL AND claim_operation_id IS NULL) OR (claim_state IN ('HELD','RECOVERY_HOLD') AND holder_actor_id IS NOT NULL AND claim_operation_id IS NOT NULL AND claim_generation>0)),
  PRIMARY KEY (tenant_id, resource_id),
  FOREIGN KEY (tenant_id, resource_id) REFERENCES dispatch_attempts (tenant_id, dispatch_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, holder_actor_id) REFERENCES actors (tenant_id, actor_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, claim_operation_id) REFERENCES operation_outcomes (tenant_id, operation_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, updated_commit_seq) REFERENCES audit_transactions (tenant_id, commit_seq) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE external_actions (
  tenant_id TEXT NOT NULL,
  action_id TEXT NOT NULL CHECK (length(action_id)=26 AND substr(action_id,1,1) BETWEEN '0' AND '7' AND action_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  resource_id TEXT NOT NULL,
  claim_generation INTEGER NOT NULL CHECK (claim_generation>0),
  holder_actor_id TEXT NOT NULL,
  authority_epoch INTEGER NOT NULL CHECK (authority_epoch>0),
  request_digest TEXT NOT NULL CHECK (length(request_digest)=64 AND request_digest NOT GLOB '*[^0123456789abcdef]*'),
  request_artifact_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('PREPARED','IN_FLIGHT','VERIFIED','NOT_APPLIED','UNKNOWN','CANCELLED')),
  created_commit_seq INTEGER NOT NULL,
  PRIMARY KEY (tenant_id, action_id),
  FOREIGN KEY (tenant_id, resource_id) REFERENCES claims (tenant_id, resource_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, holder_actor_id) REFERENCES actors (tenant_id, actor_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, request_artifact_id) REFERENCES artifacts (tenant_id, artifact_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, created_commit_seq) REFERENCES audit_transactions (tenant_id, commit_seq) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE audit_log (
  tenant_id TEXT NOT NULL,
  commit_seq INTEGER NOT NULL,
  event_ordinal INTEGER NOT NULL CHECK (event_ordinal>=0),
  event_kind TEXT NOT NULL CHECK (length(CAST(event_kind AS BLOB)) <= 80 AND instr(event_kind,char(0))=0),
  entity_id TEXT,
  prior_entity_rev INTEGER CHECK (prior_entity_rev>0),
  new_entity_rev INTEGER CHECK (new_entity_rev>0),
  event_jcs BLOB NOT NULL CHECK (length(event_jcs)<=24576 AND json_valid(CAST(event_jcs AS TEXT))),
  event_digest TEXT NOT NULL CHECK (length(event_digest)=64 AND event_digest NOT GLOB '*[^0123456789abcdef]*'),
  PRIMARY KEY (tenant_id, commit_seq, event_ordinal),
  FOREIGN KEY (tenant_id, commit_seq) REFERENCES audit_transactions (tenant_id, commit_seq) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, entity_id) REFERENCES entities (tenant_id, entity_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE INDEX audit_entity ON audit_log (tenant_id, entity_id, new_entity_rev, commit_seq);

CREATE TABLE projection_resources (
  tenant_id TEXT NOT NULL,
  generation_id TEXT NOT NULL CHECK (length(generation_id)=26 AND substr(generation_id,1,1) BETWEEN '0' AND '7' AND generation_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  spreadsheet_id TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('SPARE','BUILDING','ACTIVE','RETIRED','UNKNOWN_TARGET')),
  layout_digest TEXT NOT NULL CHECK (length(layout_digest)=64 AND layout_digest NOT GLOB '*[^0123456789abcdef]*'),
  published_commit_seq INTEGER NOT NULL CHECK (published_commit_seq>=0),
  change_next_row INTEGER NOT NULL CHECK (change_next_row>=2),
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, generation_id),
  UNIQUE (spreadsheet_id),
  FOREIGN KEY (tenant_id) REFERENCES ledger_state (tenant_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE UNIQUE INDEX one_active_projection ON projection_resources (tenant_id) WHERE state='ACTIVE';

CREATE TABLE publication_batches (
  tenant_id TEXT NOT NULL,
  batch_id TEXT NOT NULL CHECK (length(batch_id)=26 AND substr(batch_id,1,1) BETWEEN '0' AND '7' AND batch_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  generation_id TEXT NOT NULL,
  first_commit_seq INTEGER NOT NULL CHECK (first_commit_seq>0),
  last_commit_seq INTEGER NOT NULL CHECK (last_commit_seq>=first_commit_seq),
  business_rows INTEGER NOT NULL CHECK (business_rows BETWEEN 0 AND 50),
  payload_bytes INTEGER NOT NULL CHECK (payload_bytes BETWEEN 1 AND 524288),
  payload_digest TEXT NOT NULL CHECK (length(payload_digest)=64 AND payload_digest NOT GLOB '*[^0123456789abcdef]*'),
  payload_object_ref TEXT NOT NULL,
  receipt_row INTEGER NOT NULL CHECK (receipt_row>=2),
  state TEXT NOT NULL CHECK (state IN ('PREPARED','IN_FLIGHT','VERIFIED','RETRYABLE_NOT_APPLIED','UNKNOWN','QUARANTINED_PUBLICATION')),
  created_at TEXT NOT NULL,
  verified_at TEXT,
  PRIMARY KEY (tenant_id, batch_id),
  FOREIGN KEY (tenant_id, generation_id) REFERENCES projection_resources (tenant_id, generation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE sync_outbox (
  tenant_id TEXT NOT NULL,
  commit_seq INTEGER NOT NULL,
  encoded_bytes INTEGER NOT NULL CHECK (encoded_bytes BETWEEN 1 AND 262144),
  batch_id TEXT,
  state TEXT NOT NULL CHECK (state IN ('QUEUED','ASSIGNED','VERIFIED','HOLD')),
  created_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, commit_seq),
  FOREIGN KEY (tenant_id, commit_seq) REFERENCES audit_transactions (tenant_id, commit_seq) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, batch_id) REFERENCES publication_batches (tenant_id, batch_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE INDEX outbox_work ON sync_outbox (tenant_id, state, commit_seq);

CREATE TABLE delivery_events (
  delivery_event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  attempt_id TEXT NOT NULL CHECK (length(attempt_id)=26 AND substr(attempt_id,1,1) BETWEEN '0' AND '7' AND attempt_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  event_kind TEXT NOT NULL CHECK (length(CAST(event_kind AS BLOB)) <= 80 AND instr(event_kind,char(0))=0),
  recorded_at TEXT NOT NULL,
  reason_code TEXT  CHECK (length(CAST(reason_code AS BLOB)) <= 80 AND instr(reason_code,char(0))=0),
  http_status INTEGER CHECK (http_status BETWEEN 100 AND 599),
  provider_evidence_ref TEXT,
  FOREIGN KEY (tenant_id, batch_id) REFERENCES publication_batches (tenant_id, batch_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE INDEX delivery_batch ON delivery_events (tenant_id, batch_id, delivery_event_seq);

CREATE TABLE quota_reservations (
  reservation_seq INTEGER PRIMARY KEY AUTOINCREMENT,
  consumer_project TEXT NOT NULL CHECK (length(CAST(consumer_project AS BLOB)) <= 256 AND instr(consumer_project,char(0))=0),
  principal_ref TEXT NOT NULL CHECK (length(CAST(principal_ref AS BLOB)) <= 256 AND instr(principal_ref,char(0))=0),
  quota_class TEXT NOT NULL CHECK (quota_class IN ('sheets_read','sheets_write','drive_read','drive_write','token')),
  attempt_id TEXT NOT NULL CHECK (length(attempt_id)=26 AND substr(attempt_id,1,1) BETWEEN '0' AND '7' AND attempt_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  reserved_at TEXT NOT NULL,
  not_before_at TEXT NOT NULL,
  boot_id TEXT NOT NULL CHECK (length(CAST(boot_id AS BLOB)) <= 128 AND instr(boot_id,char(0))=0),
  monotonic_ns INTEGER NOT NULL CHECK (monotonic_ns>=0)
) STRICT;

CREATE INDEX quota_window ON quota_reservations (consumer_project, principal_ref, quota_class, reserved_at);

CREATE TABLE quarantine_proposals (
  tenant_id TEXT NOT NULL,
  proposal_id TEXT NOT NULL CHECK (length(proposal_id)=26 AND substr(proposal_id,1,1) BETWEEN '0' AND '7' AND proposal_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  observation_seq INTEGER NOT NULL CHECK (observation_seq>0),
  source_kind TEXT NOT NULL CHECK (source_kind IN ('sheet_scan','drive_hint','command','direct_drift')),
  source_resource_id TEXT NOT NULL,
  source_generation_id TEXT,
  source_sheet_id INTEGER,
  source_row INTEGER,
  source_column INTEGER,
  target_entity_id TEXT,
  target_field TEXT  CHECK (length(CAST(target_field AS BLOB)) <= 128 AND instr(target_field,char(0))=0),
  evidence_digest TEXT NOT NULL CHECK (length(evidence_digest)=64 AND evidence_digest NOT GLOB '*[^0123456789abcdef]*'),
  evidence_size INTEGER NOT NULL CHECK (evidence_size>=0),
  evidence_object_ref TEXT NOT NULL,
  reason_code TEXT NOT NULL CHECK (length(CAST(reason_code AS BLOB)) <= 80 AND instr(reason_code,char(0))=0),
  value_kind TEXT NOT NULL CHECK (length(CAST(value_kind AS BLOB)) <= 40 AND instr(value_kind,char(0))=0),
  base_commit_seq INTEGER CHECK (base_commit_seq>=0),
  captured_at TEXT NOT NULL,
  capture_operation_id TEXT NOT NULL,
  PRIMARY KEY (tenant_id, proposal_id),
  UNIQUE (tenant_id, observation_seq),
  FOREIGN KEY (tenant_id) REFERENCES ledger_state (tenant_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, target_entity_id) REFERENCES entities (tenant_id, entity_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, capture_operation_id) REFERENCES operation_outcomes (tenant_id, operation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE observation_heads (
  tenant_id TEXT NOT NULL,
  source_key_digest TEXT NOT NULL CHECK (length(source_key_digest)=64 AND source_key_digest NOT GLOB '*[^0123456789abcdef]*'),
  proposal_id TEXT NOT NULL,
  selection_rev INTEGER NOT NULL CHECK (selection_rev>0),
  observed_digest TEXT NOT NULL CHECK (length(observed_digest)=64 AND observed_digest NOT GLOB '*[^0123456789abcdef]*'),
  PRIMARY KEY (tenant_id, source_key_digest),
  FOREIGN KEY (tenant_id, proposal_id) REFERENCES quarantine_proposals (tenant_id, proposal_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE proposal_resolutions (
  tenant_id TEXT NOT NULL,
  proposal_id TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('ADOPT','KEEP_LOCAL','REJECT','SUPERSEDE')),
  selected_revision INTEGER NOT NULL CHECK (selected_revision>0),
  actor_id TEXT NOT NULL,
  reason_code TEXT NOT NULL CHECK (length(CAST(reason_code AS BLOB)) <= 80 AND instr(reason_code,char(0))=0),
  resolved_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, proposal_id),
  FOREIGN KEY (tenant_id, proposal_id) REFERENCES quarantine_proposals (tenant_id, proposal_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, operation_id) REFERENCES operation_outcomes (tenant_id, operation_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, actor_id) REFERENCES actors (tenant_id, actor_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE capture_checkpoints (
  tenant_id TEXT NOT NULL,
  source_key TEXT NOT NULL CHECK (length(CAST(source_key AS BLOB)) <= 512 AND instr(source_key,char(0))=0),
  cursor_value TEXT,
  dirty INTEGER NOT NULL CHECK (dirty IN (0,1)),
  last_scan_at TEXT,
  last_complete_sweep_at TEXT,
  PRIMARY KEY (tenant_id, source_key),
  FOREIGN KEY (tenant_id) REFERENCES ledger_state (tenant_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE staging_receipts (
  tenant_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  content_digest TEXT NOT NULL CHECK (length(content_digest)=64 AND content_digest NOT GLOB '*[^0123456789abcdef]*'),
  delivery_id TEXT NOT NULL,
  operation_id TEXT,
  disposition TEXT NOT NULL CHECK (disposition IN ('CAPTURED','DUPLICATE','REJECTED')),
  recorded_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, file_id, content_digest),
  FOREIGN KEY (tenant_id) REFERENCES ledger_state (tenant_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, operation_id) REFERENCES operation_outcomes (tenant_id, operation_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE projection_rows (
  tenant_id TEXT NOT NULL,
  generation_id TEXT NOT NULL,
  tab_key TEXT NOT NULL CHECK (tab_key IN ('directory','active_pipeline','completed_archives')),
  entity_id TEXT NOT NULL,
  sheet_id INTEGER NOT NULL CHECK (sheet_id>=0),
  row_index INTEGER NOT NULL CHECK (row_index>=2),
  projection_seq INTEGER NOT NULL CHECK (projection_seq>=0),
  row_digest TEXT CHECK (length(row_digest)=64 AND row_digest NOT GLOB '*[^0123456789abcdef]*'),
  PRIMARY KEY (tenant_id, generation_id, tab_key, entity_id),
  UNIQUE (tenant_id, generation_id, sheet_id, row_index),
  FOREIGN KEY (tenant_id, generation_id) REFERENCES projection_resources (tenant_id, generation_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, entity_id) REFERENCES entities (tenant_id, entity_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE entity_search_documents (
  search_doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  entity_kind TEXT NOT NULL,
  display_name TEXT NOT NULL CHECK (length(CAST(display_name AS BLOB)) <= 1024 AND instr(display_name,char(0))=0),
  aliases TEXT NOT NULL CHECK (length(CAST(aliases AS BLOB)) <= 4096 AND instr(aliases,char(0))=0),
  organization_name TEXT NOT NULL CHECK (length(CAST(organization_name AS BLOB)) <= 1024 AND instr(organization_name,char(0))=0),
  summary TEXT NOT NULL CHECK (length(CAST(summary AS BLOB)) <= 2048 AND instr(summary,char(0))=0),
  next_action TEXT NOT NULL CHECK (length(CAST(next_action AS BLOB)) <= 1024 AND instr(next_action,char(0))=0),
  source_entity_rev INTEGER NOT NULL CHECK (source_entity_rev>0),
  source_projection_seq INTEGER NOT NULL CHECK (source_projection_seq>0),
  search_generation INTEGER NOT NULL CHECK (search_generation>0),
  CHECK (length(CAST(display_name||aliases||organization_name||summary||next_action AS BLOB))<=8192),
  UNIQUE (tenant_id, entity_id),
  UNIQUE (tenant_id, search_doc_id),
  FOREIGN KEY (tenant_id, entity_id, entity_kind) REFERENCES entities (tenant_id, entity_id, entity_kind) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, entity_id, source_entity_rev) REFERENCES entity_versions (tenant_id, entity_id, entity_rev) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE interaction_search_documents (
  search_doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  interaction_id TEXT NOT NULL,
  patron_id TEXT NOT NULL,
  communication_thread_id TEXT,
  subject TEXT NOT NULL CHECK (length(CAST(subject AS BLOB)) <= 512 AND instr(subject,char(0))=0),
  participants TEXT NOT NULL CHECK (length(CAST(participants AS BLOB)) <= 1536 AND instr(participants,char(0))=0),
  summary TEXT NOT NULL CHECK (length(CAST(summary AS BLOB)) <= 2048 AND instr(summary,char(0))=0),
  excerpt TEXT NOT NULL CHECK (length(CAST(excerpt AS BLOB)) <= 4096 AND instr(excerpt,char(0))=0),
  occurred_at TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  source_commit_seq INTEGER NOT NULL CHECK (source_commit_seq>0),
  search_generation INTEGER NOT NULL CHECK (search_generation>0),
  CHECK (length(CAST(subject||participants||summary||excerpt AS BLOB))<=8192),
  UNIQUE (tenant_id, interaction_id),
  FOREIGN KEY (tenant_id, interaction_id) REFERENCES interactions (tenant_id, interaction_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, patron_id) REFERENCES patrons (tenant_id, patron_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, communication_thread_id) REFERENCES communication_threads (tenant_id, thread_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE name_grams (
  tenant_id TEXT NOT NULL,
  normalizer_version TEXT NOT NULL,
  gram TEXT NOT NULL CHECK (length(gram)=3),
  search_doc_id INTEGER NOT NULL,
  PRIMARY KEY (tenant_id, normalizer_version, gram, search_doc_id),
  FOREIGN KEY (tenant_id, search_doc_id) REFERENCES entity_search_documents (tenant_id, search_doc_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE legacy_identifiers (
  tenant_id TEXT NOT NULL,
  identifier_scheme TEXT NOT NULL CHECK (length(CAST(identifier_scheme AS BLOB)) <= 80 AND instr(identifier_scheme,char(0))=0),
  original_value TEXT NOT NULL CHECK (length(CAST(original_value AS BLOB)) <= 512 AND instr(original_value,char(0))=0),
  entity_id TEXT NOT NULL,
  PRIMARY KEY (tenant_id, identifier_scheme, original_value),
  FOREIGN KEY (tenant_id, entity_id) REFERENCES entities (tenant_id, entity_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE snapshot_manifests (
  tenant_id TEXT NOT NULL,
  snapshot_id TEXT NOT NULL CHECK (length(snapshot_id)=26 AND substr(snapshot_id,1,1) BETWEEN '0' AND '7' AND snapshot_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  terminal_commit_seq INTEGER NOT NULL CHECK (terminal_commit_seq>=0),
  manifest_digest TEXT NOT NULL CHECK (length(manifest_digest)=64 AND manifest_digest NOT GLOB '*[^0123456789abcdef]*'),
  object_ref TEXT NOT NULL,
  signer_key_id TEXT NOT NULL,
  ed25519_signature BLOB NOT NULL CHECK (length(ed25519_signature)=64),
  verified_at TEXT NOT NULL,
  PRIMARY KEY (tenant_id, snapshot_id),
  FOREIGN KEY (tenant_id) REFERENCES ledger_state (tenant_id) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE schema_migrations (
  version INTEGER PRIMARY KEY CHECK (version>0),
  ddl_digest TEXT NOT NULL CHECK (length(ddl_digest)=64 AND ddl_digest NOT GLOB '*[^0123456789abcdef]*'),
  applied_at TEXT NOT NULL,
  previous_snapshot_id TEXT,
  evidence_ref TEXT NOT NULL
) STRICT;

CREATE TABLE telemetry_contracts (
  tenant_id TEXT NOT NULL,
  contract_id TEXT NOT NULL CHECK (length(CAST(contract_id AS BLOB)) <= 128 AND instr(contract_id,char(0))=0),
  producer_digest TEXT NOT NULL CHECK (length(producer_digest)=64 AND producer_digest NOT GLOB '*[^0123456789abcdef]*'),
  contract_jcs BLOB NOT NULL CHECK (length(contract_jcs)<=24576 AND json_valid(CAST(contract_jcs AS TEXT))),
  accepted_commit_seq INTEGER NOT NULL,
  PRIMARY KEY (tenant_id, contract_id),
  FOREIGN KEY (tenant_id) REFERENCES ledger_state (tenant_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, accepted_commit_seq) REFERENCES audit_transactions (tenant_id, commit_seq) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE TABLE telemetry_events (
  tenant_id TEXT NOT NULL,
  sample_id TEXT NOT NULL CHECK (length(sample_id)=26 AND substr(sample_id,1,1) BETWEEN '0' AND '7' AND sample_id NOT GLOB '*[^0123456789ABCDEFGHJKMNPQRSTVWXYZ]*'),
  contract_id TEXT NOT NULL,
  source_id TEXT NOT NULL CHECK (length(CAST(source_id AS BLOB)) <= 128 AND instr(source_id,char(0))=0),
  run_id TEXT NOT NULL CHECK (length(CAST(run_id AS BLOB)) <= 128 AND instr(run_id,char(0))=0),
  source_seq INTEGER NOT NULL CHECK (source_seq>=0),
  observed_at TEXT NOT NULL,
  received_at TEXT NOT NULL,
  sample_jcs BLOB NOT NULL CHECK (length(sample_jcs)<=24576 AND json_valid(CAST(sample_jcs AS TEXT))),
  sample_digest TEXT NOT NULL CHECK (length(sample_digest)=64 AND sample_digest NOT GLOB '*[^0123456789abcdef]*'),
  supersedes_sample_id TEXT,
  commit_seq INTEGER NOT NULL,
  PRIMARY KEY (tenant_id, sample_id),
  UNIQUE (tenant_id, source_id, run_id, source_seq),
  FOREIGN KEY (tenant_id, contract_id) REFERENCES telemetry_contracts (tenant_id, contract_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, supersedes_sample_id) REFERENCES telemetry_events (tenant_id, sample_id) DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY (tenant_id, commit_seq) REFERENCES audit_transactions (tenant_id, commit_seq) DEFERRABLE INITIALLY DEFERRED
) STRICT;

CREATE VIRTUAL TABLE entity_fts USING fts5(
  tenant_id UNINDEXED,
  entity_id UNINDEXED,
  entity_kind UNINDEXED,
  display_name,
  aliases,
  organization_name,
  summary,
  next_action,
  source_entity_rev UNINDEXED,
  source_projection_seq UNINDEXED,
  search_generation UNINDEXED,
  tokenize='unicode61 remove_diacritics 2', detail=full, prefix='2 3 4'
);

CREATE VIRTUAL TABLE interaction_fts USING fts5(
  tenant_id UNINDEXED,
  interaction_id UNINDEXED,
  patron_id UNINDEXED,
  communication_thread_id UNINDEXED,
  subject,
  participants,
  summary,
  excerpt,
  occurred_at UNINDEXED,
  recorded_at UNINDEXED,
  source_commit_seq UNINDEXED,
  search_generation UNINDEXED,
  tokenize='unicode61 remove_diacritics 2', detail=full
);

CREATE TRIGGER audit_transactions_no_update BEFORE UPDATE ON audit_transactions
BEGIN
  SELECT RAISE(ABORT, 'audit_transactions: append-only');
END;

CREATE TRIGGER audit_transactions_no_delete BEFORE DELETE ON audit_transactions
BEGIN
  SELECT RAISE(ABORT, 'audit_transactions: append-only');
END;

CREATE TRIGGER operation_outcomes_no_update BEFORE UPDATE ON operation_outcomes
BEGIN
  SELECT RAISE(ABORT, 'operation_outcomes: append-only');
END;

CREATE TRIGGER operation_outcomes_no_delete BEFORE DELETE ON operation_outcomes
BEGIN
  SELECT RAISE(ABORT, 'operation_outcomes: append-only');
END;

CREATE TRIGGER entity_versions_no_update BEFORE UPDATE ON entity_versions
BEGIN
  SELECT RAISE(ABORT, 'entity_versions: append-only');
END;

CREATE TRIGGER entity_versions_no_delete BEFORE DELETE ON entity_versions
BEGIN
  SELECT RAISE(ABORT, 'entity_versions: append-only');
END;

CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN
  SELECT RAISE(ABORT, 'audit_log: append-only');
END;

CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN
  SELECT RAISE(ABORT, 'audit_log: append-only');
END;

CREATE TRIGGER artifacts_no_update BEFORE UPDATE ON artifacts
BEGIN
  SELECT RAISE(ABORT, 'artifacts: append-only');
END;

CREATE TRIGGER artifacts_no_delete BEFORE DELETE ON artifacts
BEGIN
  SELECT RAISE(ABORT, 'artifacts: append-only');
END;

CREATE TRIGGER interactions_no_update BEFORE UPDATE ON interactions
BEGIN
  SELECT RAISE(ABORT, 'interactions: append-only');
END;

CREATE TRIGGER interactions_no_delete BEFORE DELETE ON interactions
BEGIN
  SELECT RAISE(ABORT, 'interactions: append-only');
END;

CREATE TRIGGER thread_chunks_no_update BEFORE UPDATE ON thread_chunks
BEGIN
  SELECT RAISE(ABORT, 'thread_chunks: append-only');
END;

CREATE TRIGGER thread_chunks_no_delete BEFORE DELETE ON thread_chunks
BEGIN
  SELECT RAISE(ABORT, 'thread_chunks: append-only');
END;

CREATE TRIGGER delivery_events_no_update BEFORE UPDATE ON delivery_events
BEGIN
  SELECT RAISE(ABORT, 'delivery_events: append-only');
END;

CREATE TRIGGER delivery_events_no_delete BEFORE DELETE ON delivery_events
BEGIN
  SELECT RAISE(ABORT, 'delivery_events: append-only');
END;

CREATE TRIGGER quota_reservations_no_update BEFORE UPDATE ON quota_reservations
BEGIN
  SELECT RAISE(ABORT, 'quota_reservations: append-only');
END;

CREATE TRIGGER quota_reservations_no_delete BEFORE DELETE ON quota_reservations
BEGIN
  SELECT RAISE(ABORT, 'quota_reservations: append-only');
END;

CREATE TRIGGER quarantine_proposals_no_update BEFORE UPDATE ON quarantine_proposals
BEGIN
  SELECT RAISE(ABORT, 'quarantine_proposals: append-only');
END;

CREATE TRIGGER quarantine_proposals_no_delete BEFORE DELETE ON quarantine_proposals
BEGIN
  SELECT RAISE(ABORT, 'quarantine_proposals: append-only');
END;

CREATE TRIGGER proposal_resolutions_no_update BEFORE UPDATE ON proposal_resolutions
BEGIN
  SELECT RAISE(ABORT, 'proposal_resolutions: append-only');
END;

CREATE TRIGGER proposal_resolutions_no_delete BEFORE DELETE ON proposal_resolutions
BEGIN
  SELECT RAISE(ABORT, 'proposal_resolutions: append-only');
END;

CREATE TRIGGER staging_receipts_no_update BEFORE UPDATE ON staging_receipts
BEGIN
  SELECT RAISE(ABORT, 'staging_receipts: append-only');
END;

CREATE TRIGGER staging_receipts_no_delete BEFORE DELETE ON staging_receipts
BEGIN
  SELECT RAISE(ABORT, 'staging_receipts: append-only');
END;

CREATE TRIGGER legacy_identifiers_no_update BEFORE UPDATE ON legacy_identifiers
BEGIN
  SELECT RAISE(ABORT, 'legacy_identifiers: append-only');
END;

CREATE TRIGGER legacy_identifiers_no_delete BEFORE DELETE ON legacy_identifiers
BEGIN
  SELECT RAISE(ABORT, 'legacy_identifiers: append-only');
END;

CREATE TRIGGER snapshot_manifests_no_update BEFORE UPDATE ON snapshot_manifests
BEGIN
  SELECT RAISE(ABORT, 'snapshot_manifests: append-only');
END;

CREATE TRIGGER snapshot_manifests_no_delete BEFORE DELETE ON snapshot_manifests
BEGIN
  SELECT RAISE(ABORT, 'snapshot_manifests: append-only');
END;

CREATE TRIGGER schema_migrations_no_update BEFORE UPDATE ON schema_migrations
BEGIN
  SELECT RAISE(ABORT, 'schema_migrations: append-only');
END;

CREATE TRIGGER schema_migrations_no_delete BEFORE DELETE ON schema_migrations
BEGIN
  SELECT RAISE(ABORT, 'schema_migrations: append-only');
END;

CREATE TRIGGER telemetry_contracts_no_update BEFORE UPDATE ON telemetry_contracts
BEGIN
  SELECT RAISE(ABORT, 'telemetry_contracts: append-only');
END;

CREATE TRIGGER telemetry_contracts_no_delete BEFORE DELETE ON telemetry_contracts
BEGIN
  SELECT RAISE(ABORT, 'telemetry_contracts: append-only');
END;

CREATE TRIGGER telemetry_events_no_update BEFORE UPDATE ON telemetry_events
BEGIN
  SELECT RAISE(ABORT, 'telemetry_events: append-only');
END;

CREATE TRIGGER telemetry_events_no_delete BEFORE DELETE ON telemetry_events
BEGIN
  SELECT RAISE(ABORT, 'telemetry_events: append-only');
END;

CREATE TRIGGER entities_no_delete BEFORE DELETE ON entities
BEGIN SELECT RAISE(ABORT,'entities: tombstone required'); END;
CREATE TRIGGER entities_identity_fixed BEFORE UPDATE OF tenant_id,entity_id,entity_kind ON entities
WHEN NEW.tenant_id<>OLD.tenant_id OR NEW.entity_id<>OLD.entity_id OR NEW.entity_kind<>OLD.entity_kind
BEGIN SELECT RAISE(ABORT,'entities: immutable identity'); END;
CREATE TRIGGER entities_revision_step BEFORE UPDATE ON entities
WHEN NEW.entity_rev<>OLD.entity_rev+1 OR NEW.last_commit_seq<=OLD.last_commit_seq
BEGIN SELECT RAISE(ABORT,'entities: revision/commit must advance'); END;
CREATE TRIGGER claims_generation_guard BEFORE UPDATE ON claims
WHEN NEW.claim_generation<OLD.claim_generation OR
 (OLD.claim_state='UNCLAIMED' AND NEW.claim_state='HELD' AND NEW.claim_generation<>OLD.claim_generation+1) OR
 (OLD.claim_state IN ('HELD','RECOVERY_HOLD') AND NEW.claim_state='HELD' AND
  (NEW.holder_actor_id IS NOT OLD.holder_actor_id OR NEW.claim_generation<>OLD.claim_generation))
BEGIN SELECT RAISE(ABORT,'claims: invalid takeover/generation'); END;
CREATE TRIGGER claims_no_delete BEFORE DELETE ON claims
BEGIN SELECT RAISE(ABORT,'claims: preserve generation'); END;

CREATE INDEX dispatch_work ON dispatch_attempts (tenant_id, work_item_id, attempt_no);

CREATE INDEX actions_resource ON external_actions (tenant_id, resource_id, state);

CREATE INDEX proposal_target ON quarantine_proposals (tenant_id, target_entity_id, observation_seq);

CREATE INDEX staging_delivery ON staging_receipts (tenant_id, delivery_id);

CREATE INDEX telemetry_order ON telemetry_events (tenant_id, source_id, run_id, source_seq);
