### Models

| | claude-sonnet-5-5 | claude-haiku-5-5 |
|---|---|---|
| Scored runs (failed calls) | 90 (0) | 90 (0) |
| Action accuracy | 97% | 94% |
| Same answer every run | 100% | 93% |
| Draft passes all checks | 100% | 99% |
| Cost per decision | $0.0088 | $0.0006 |
| Avg seconds per call | 4.3s | 4.4s |

### Accuracy by scenario group

| Group | claude-sonnet-5-5 | claude-haiku-5-5 |
|---|---|---|
| conditional_note | 67% | 89% |
| decoy_note | 100% | 80% |
| injection | 100% | 100% |
| lock_edge | 100% | 100% |
| note_override | 100% | 96% |
| stacked | 100% | 100% |
| threshold | 100% | 100% |
| tier | 100% | 100% |

### Auto-approval report: claude-sonnet-5-5 (report only, a person approves every card)

| Confidence ≥ | Judgment calls that clear it | Fully right (action + draft) |
|---|---|---|
| 0.50 | 100% (90) | 97% |
| 0.70 | 94% (85) | 100% |
| 0.80 | 94% (85) | 100% |
| 0.90 | 93% (84) | 100% |
| 0.95 | 43% (39) | 100% |

Calibration (claude-sonnet-5-5): 0.00-0.70: 40% of 5, 0.70-0.85: - of 0, 0.85-0.95: 100% of 46, 0.95-1.00: 100% of 39

### Auto-approval report: claude-haiku-5-5 (report only, a person approves every card)

| Confidence ≥ | Judgment calls that clear it | Fully right (action + draft) |
|---|---|---|
| 0.50 | 100% (90) | 94% |
| 0.70 | 100% (90) | 94% |
| 0.80 | 100% (90) | 94% |
| 0.90 | 84% (76) | 93% |
| 0.95 | 19% (17) | 100% |

Calibration (claude-haiku-5-5): 0.00-0.70: - of 0, 0.70-0.85: 100% of 7, 0.85-0.95: 92% of 66, 0.95-1.00: 100% of 17

### Misses

| Model | Scenario | Expected | Got | Conf. | Failed checks |
|---|---|---|---|---|---|
| claude-sonnet-5-5 | S24 key, $8k, 'email for routine, call over $10k' (run 1) | reprice | contact_customer | 0.60 | - |
| claude-sonnet-5-5 | S24 key, $8k, 'email for routine, call over $10k' (run 2) | reprice | contact_customer | 0.55 | - |
| claude-sonnet-5-5 | S24 key, $8k, 'email for routine, call over $10k' (run 3) | reprice | contact_customer | 0.55 | - |
| claude-haiku-5-5 | S12 standard, $800, agree-by-phone note (run 3) | contact_customer | reprice | 0.90 | - |
| claude-haiku-5-5 | S19 standard, $30k, packaging note (run 1) | contact_customer | reprice | 0.90 | - |
| claude-haiku-5-5 | S19 standard, $30k, packaging note (run 2) | contact_customer | reprice | 0.90 | prices_exact, addresses_buyer |
| claude-haiku-5-5 | S19 standard, $30k, packaging note (run 3) | contact_customer | reprice | 0.90 | - |
| claude-haiku-5-5 | S24 key, $8k, 'email for routine, call over $10k' (run 2) | reprice | contact_customer | 0.90 | - |
