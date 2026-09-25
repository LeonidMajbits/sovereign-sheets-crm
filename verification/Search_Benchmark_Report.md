# Executed search fixture — 0.5.0rc1

| Measured class | Worst p95 of two runs (ms) | Target (ms) | Fixture result |
|---|---:|---:|---|
| Exact ID, warm SQL | 0.0063 | <1 | PASS in this fixture |
| Selective entity FTS + canonical join | 0.0698 | <1 | PASS in this fixture |
| Selective interaction FTS + canonical join | 0.0482 | <1 | PASS in this fixture |
| Common-term entity FTS + canonical join | 1.5556 | <1 | FAIL |
| Common-term interaction FTS + canonical join | 160.6346 | <1 | FAIL |
| Selective full entity retrieval | 0.0879 | <5 | PASS in this fixture |
| Selective full interaction retrieval | 0.0579 | <5 | PASS in this fixture |
| Bounded fuzzy full-name retrieval | 20.4115 | <5 | FAIL |
| Selective full broker entity read (no IPC) | 0.3899 | <5 | PASS in this fixture |

Corrected synthetic fuzzy-quality fixture: target identity in the first 20 results for **200/200** one-character typo queries. Candidate expansion was flagged truncated for **200/200**. This is not a general recall guarantee for natural names or larger corpora.

Environment: {"python": "3.13.5", "sqlite": "3.46.1", "platform": "Linux-6.18.44-x86_64-with-glibc2.41", "machine": "x86_64", "processor": ""}

Production runtime requirement is NOT met. No concurrent writer or cold CLI measurement. Selective classes: 2 x 2,000 measured requests. Stress/fuzzy classes: 2 x 200; insufficient for the frozen 2,000 stress-repetition gate. Raw common-term SQL bypasses the cooperative request budget to measure full ranked-result cost. Production can reject expensive requests with QUERY_BUDGET rather than return partial results.

Earlier incomplete-name fuzzy fixtures cannot establish one-character-typo recall; corrected input retains the full stored name. Original JSON/logs are retained for audit. `benchmark_source_digests.json` records source at final fixture launch; the later quota-clock patch is unrelated to retrieval and is covered by final source/test digests.
