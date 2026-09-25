-- Additive operational extension; frozen v4 business DDL remains byte-identical.
CREATE TABLE runtime_state(key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
CREATE TABLE entity_tags (
 tenant_id TEXT NOT NULL, entity_id TEXT NOT NULL, tag TEXT NOT NULL,
 introduced_commit_seq INTEGER NOT NULL,
 PRIMARY KEY(tenant_id,entity_id,tag),
 FOREIGN KEY(tenant_id,entity_id) REFERENCES entities(tenant_id,entity_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(tenant_id,introduced_commit_seq) REFERENCES audit_transactions(tenant_id,commit_seq) DEFERRABLE INITIALLY DEFERRED,
 CHECK(length(CAST(tag AS BLOB)) BETWEEN 1 AND 128)
) STRICT;
CREATE TABLE projection_slots(
 generation_id TEXT NOT NULL, sheet_id INTEGER NOT NULL, row_index INTEGER NOT NULL,
 entity_id TEXT NOT NULL, retired INTEGER NOT NULL CHECK(retired IN (0,1)),
 PRIMARY KEY(generation_id,sheet_id,row_index)
) STRICT;
CREATE TABLE projection_shadows(
 generation_id TEXT NOT NULL, sheet_id INTEGER NOT NULL, row_index INTEGER NOT NULL,
 cells_jcs BLOB NOT NULL, PRIMARY KEY(generation_id,sheet_id,row_index)
) STRICT;
CREATE TABLE local_nonces(
 principal TEXT NOT NULL, nonce TEXT NOT NULL, expires_at TEXT NOT NULL,
 PRIMARY KEY(principal,nonce)
) STRICT;
