# Explicit Lamport field policy — v6

The v4/v5 conditional command protocol remains the default. `entity.lww.set` is a new, separately authorized (`entity.lww`) local command. It is not a redefinition of `entity.patch`, a fallback after conflict, or permission for a Sheet editor to invent a base.

## Admitted fields and identities

Only `note` and `next_action` on live person, organization, campaign and project entities are admitted. Status, identity, ownership, claim generations, amount/currency, stage acceptance and all external actions remain guarded by their original templates. The optional Apps Script bridge still accepts its older bounded schema; v6 Lamport packets are local-broker-only until a separate bridge upgrade is implemented and tested.

The authenticated actor—not an actor string in the payload—supplies the source identity. The rank is the lexicographic tuple `(logical_clock as integer, authenticated_actor_id, operation_id)`. A sender following Lamport clock discipline advances its local clock before sending and beyond a received `receive_clock` before its next causally subsequent send. The receiver records `max(previous_receive_clock, incoming_clock)+1`; exhaustion fails closed. This is logical priority, not a wall-clock timestamp or proof of what a human saw. Authorized actors are trusted to obey sender clock discipline; a large permitted clock can dominate these fields. Tie-breaking makes even equal source counters deterministic, not proof that their sender implemented a strict clock.

## Selection, history and ownership

For a fixed set C of admitted candidates, the selected value belongs to `max(C, key=rank)`. Max under this total order is associative, commutative and idempotent. Independent arrival orders therefore select the same winner. Audit order, receiver clocks and the number of intermediate canonical revisions may differ.

Every admitted candidate, including a loser, becomes an immutable `lamport.candidate` audit event and an outbox obligation. A loser is recorded without replacing the selected canonical field. An identical-value winner advances the register head without inventing a canonical entity revision. Exact operation retries return the original outcome without another event. Same operation identity/different bytes is rejected.

The first use validates an authentic retained base with an unchanged field. It establishes LWW ownership for that field in reserved `runtime_state` metadata. Later ordinary based patches (including raw-note adoption through that path) receive `LWW_FIELD_OWNED`; they cannot secretly bypass the selected policy. Other fields remain independently writable. Version 1 has no automatic field-policy reset or clock reset. Choose the mode deliberately, and retain the metadata in backups.

All candidate validation, head/receiver-clock updates, selected canonical changes, FTS, audit and outbox occur in the same real `Engine.ingest` transaction. The frozen v4 DDL remains byte-identical; no generic EAV business store or second authority is added.

## What the zero claims mean

A last-write-wins register necessarily replaces prior current values. The qualified safety claim is no unrecorded loss of admitted candidates and no unauthorized-field overwrite—not that competing values all remain current in one cell.

LWW does not conserve balances. With a balance of 100 and two independent 80-unit debits, both can propose 20; selecting one remaining-balance value does not prevent 160 units of side effects. The CRM neither exposes financial LWW nor processes payments. Its idempotent command effects and fenced exclusive claims are tested separately. Financial settlement and external exactly-once execution are not certified.
