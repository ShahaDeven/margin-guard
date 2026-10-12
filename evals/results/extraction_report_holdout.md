| Email | Trap | Gold | Got | Changes (material / $/lb / date) |
|---|---|---|---|---|
| H01 | prices in a text table, US date format | detected | PASS detected | MAT-NBR-70 y/y/y; MAT-NBR-90 y/y/y |
| H02 | priced per thousand lb (M) | detected | PASS detected | MAT-CB-N550 y/y/y |
| H03 | a correction: the old wrong price appears first | detected | PASS detected | MAT-VMQ-50 y/y/y |
| H04 | reply thread quoting the old price twice | detected | PASS detected | MAT-SBR-60 y/y/y |
| H05 | distributor mentions another vendor and an unchanged grade | detected | PASS detected | MAT-EPDM-70 y/y/y |
| H06 | relative date ('first of next month', received Oct 16) | detected | PASS detected | MAT-FKM-75 y/y/y |
| H07 | price in cents | detected | FAIL needs_review | MAT-CB-N550 n/n/n |
| H08 | temporary surcharge, not a new list price | needs_review | PASS needs_review | - |
| H09 | percentage decrease | detected | PASS detected | MAT-NR-40 y/y/y |
| H10 | shipping confirmation with a price in it | ignored | PASS ignored | - |

- Outcome accuracy: **90%** (10 emails)
- Change recall: **89%**, price within 0.5%: **89%**, date exact: **89%** (9 gold changes)
- Unexpected changes emitted: **0**
