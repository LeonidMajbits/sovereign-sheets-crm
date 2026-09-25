# v1.0.0 qualification disposition

The package is a release target with explicit qualification evidence, not a waiver of its production gates. The original v5 conformance record is byte-preserved in `baseline/Turn_05_CONFORMANCE.md` and the original archive.

## Implemented and exercised

The source retains one tenant/file authority; v4 DDL is unchanged. Turn 6 adds a bounded local Lamport prose-register command, actual jitter, equivalent canonical encoding, new regressions and the qualification harness. The main matrix exercises real WAL/FULL commits through `Engine.ingest`, not direct seed-table writes, followed by exact retries and the real Publisher over an independent typed provider model. Administrative actor registration is fixture setup and is excluded from the 50,000 primary commands.

Ten tenants have separate workbook resources and databases, but share an effective quota domain. All workers of a tenant share its tabs. This is not a qualification of hostile customer tenants intermingled in one workbook. The latter would violate the baseline disclosure boundary and require a separate product design.

The strict current-value notion of "zero overwrite" is incompatible with updates and LWW. The tested notions are zero missing accepted operations/revisions, zero duplicate canonical effects on retry, preserved losing LWW candidates, no publication into human-owned columns, and correct exclusive claims. No financial processor or arbitrary external exactly-once sink is certified.

## Still not established

- Python-linked SQLite >=3.51.3 and actual Darwin ARM64/APFS crash/durability behavior on ZION. Delivered compatibility evidence does not close this gate.
- Live Google credentials, permissions, unattended token renewal, service quotas, deployed trigger execution and network readback. The artifact upload is not a CRM cloud integration test.
- The previously failed broad/common-term/fuzzy latency gates. The full fixed-fixture target rerun is included in `qualification/qualify_target.sh`.
- Automatic replacement-workbook cutover, existing unrelated DB migration, real external executor fencing and encrypted backup storage. Existing fail-closed behavior remains; unsupported paths are not silently implemented by the test harness.
- v6 command admission through the optional Apps Script bridge. The local broker extension is explicit; old remote protocols reject unknown alternatives.

Original planning obligations remain in the retained baseline. New evidence files identify the specific paths exercised; they do not mark all historical obligations PASS merely because a related mock succeeded. Source hashes, host/runtime, fixture boundaries and measured failures are part of every usable claim.
