# Primary references used during Turn 5

Checked 23 September 2026. These references establish platform behavior, not the behavior or measured performance of this code. Original Turn 4 references remain in the preserved baseline.

| Reference | Use |
|---|---|
| https://sqlite.org/wal.html | Local WAL premises, FULL/checkpoint behavior, documented WAL-reset fix motivating the frozen linked-runtime floor |
| https://sqlite.org/lang_transaction.html | Serialized writers and immediate transactions; application eligibility predicates remain necessary |
| https://sqlite.org/fts5.html | Unicode61, BM25 and content-bearing FTS mechanics; no latency guarantee |
| https://developers.google.com/workspace/sheets/api/limits | Shared read/write quotas, payload guidance and throttling |
| https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/cells | Typed user-entered versus effective/formatted cell values |
| https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/batchUpdate | Atomic request application, not cross-system row compare-and-swap |
| https://developers.google.com/apps-script/guides/triggers/installable | Standalone installed edit/change triggers and creator authorization |
| https://developers.google.com/apps-script/reference/content/text-output | Structured JSON body, no general arbitrary HTTP status setter |
| https://developers.google.com/identity/protocols/oauth2/service-account | Documented service-account JWT/access-token flow |
| https://www.rfc-editor.org/rfc/rfc8785 | Canonical JSON; code implements a bounded integer-only interoperable profile |
| https://www.rfc-editor.org/rfc/rfc8032 | Ed25519 detached snapshot signatures with independently pinned verification key |

The code does not rely on third-party SaaS, browser automation or a Google-side custom row-lock API.
