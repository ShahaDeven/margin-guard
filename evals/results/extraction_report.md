| Email | Trap | Gold | Got | Changes (material / $/lb / date) |
|---|---|---|---|---|
| E01 | clean baseline | detected | PASS detected | MAT-EPDM-70 y/y/y |
| E02 | priced per kg; catalog is per lb | detected | PASS detected | MAT-NBR-70 y/y/y |
| E03 | pack pricing: per 25 kg bag | detected | PASS detected | MAT-VMQ-50 y/y/y |
| E04 | forwarded duplicate of E01 from a different address | duplicate | PASS duplicate | - |
| E05 | price decrease, not an increase | detected | PASS detected | MAT-CR-60 y/y/y |
| E06 | irrelevant email that mentions pricing | ignored | PASS ignored | - |
| E07 | ambiguous name: Keystone supplies both EPDM 70 and NBR 70 as 'Black 70' | needs_review | PASS needs_review | - |
| E08 | percentage only; new price must be computed from our current cost | detected | PASS detected | MAT-FKM-75 y/y/y |
| E09 | priced per hundredweight (cwt) | detected | PASS detected | MAT-CB-N550 y/y/y |
| E10 | priced per metric ton | detected | PASS detected | MAT-STL-1018 y/y/y |
| E11 | effective date after most open quotes expire | detected | PASS detected | MAT-NR-40 y/y/y |
| E12 | two changes in one email, plus a decoy mention of other grades | detected | PASS detected | MAT-EPDM-50 y/y/y; MAT-SBR-60 y/y/y |
| E13 | change already applied on Oct 1 | duplicate | PASS duplicate | - |
| E14 | sales offer from a supplier we do not use, not a cost change | ignored | PASS ignored | - |
| E15 | advisory with a range and no exact price or date | needs_review | PASS needs_review | - |

- Outcome accuracy: **100%** (15 emails)
- Change recall: **100%**, price within 0.5%: **100%**, date exact: **100%** (10 gold changes)
- Unexpected changes emitted: **0**
