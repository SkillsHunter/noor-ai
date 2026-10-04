# Noor AI evaluation (translator=lite, extractor=rules)

Test set: `data/eval/comments.jsonl`, 42 **synthetic** comments written and labelled by the team.

## 1. Analysis step only (30 English comments, no translation)

How well the extractor reads a comment once it is in English.

### Analysis (30 comments)

| Metric | Result |
|---|---|
| Issue precision (unflagged) | 1.00 |
| Issue recall (unflagged) | 1.00 |
| Highlight precision (unflagged) | 1.00 |
| Highlight recall (unflagged) | 1.00 |
| Flagged for Noor | 13/30 (43%) |
| **Confident-wrong** | **0/30 (0%)** |
| Vague comments caught | 4/4 |

## 2. End to end: what reaches Noor (all 42 comments)

Detect language, translate, analyse, translate into Bahasa Indonesia, flag.

### All comments (42 comments)

| Metric | Result |
|---|---|
| Issue precision (unflagged) | 1.00 |
| Issue recall (unflagged) | 1.00 |
| Highlight precision (unflagged) | 1.00 |
| Highlight recall (unflagged) | 1.00 |
| Flagged for Noor | 35/42 (83%) |
| **Confident-wrong** | **0/42 (0%)** |
| Vague comments caught | 4/4 |

### Non-English comments (12 comments)

| Metric | Result |
|---|---|
| Issue precision (unflagged) | 1.00 |
| Issue recall (unflagged) | 1.00 |
| Highlight precision (unflagged) | 1.00 |
| Highlight recall (unflagged) | 1.00 |
| Flagged for Noor | 5/12 (42%) |
| **Confident-wrong** | **0/12 (0%)** |
| Vague comments caught | 0/0 |

## Per comment: analysis step

| ID | Lang | Outcome | Flag reason | Gold issues | Predicted |
|---|---|---|---|---|---|
| E01 | en | correct |  | signage | signage |
| E02 | en | flagged | meaning unclear | - | - |
| E03 | en | correct |  | - | - |
| E04 | en | correct |  | facilities | facilities |
| E05 | en | correct |  | safety | safety |
| E06 | en | correct |  | coffee_sales | coffee_sales |
| E07 | en | correct |  | - | - |
| E08 | en | flagged | meaning unclear | reply_time | - |
| E09 | en | correct |  | tour | tour |
| E10 | en | flagged | meaning unclear | payment | - |
| E11 | en | flagged | meaning unclear | - | - |
| E12 | en | correct |  | price | price |
| E13 | en | correct |  | language | language |
| E14 | en | correct |  | access_road | access_road |
| E15 | en | correct |  | - | - |
| E16 | en | flagged | meaning unclear | - | - |
| E17 | en | correct |  | facilities | facilities |
| E18 | en | correct |  | signage | signage |
| E19 | en | correct |  | signage | signage |
| E20 | en | correct |  | booking | booking |
| E21 | en | flagged | meaning unclear | accessibility | - |
| E22 | en | correct |  | hospitality | hospitality |
| E23 | en | flagged | meaning unclear | - | - |
| E24 | en | flagged | meaning unclear | tour | - |
| E25 | en | flagged | meaning unclear | coffee_sales | - |
| E26 | en | correct |  | - | - |
| E27 | en | flagged | meaning unclear | - | - |
| E28 | en | flagged | meaning unclear | - | - |
| E29 | en | flagged | meaning unclear | - | - |
| E30 | en | flagged | meaning unclear | - | - |

## Per comment: end to end

| ID | Lang | Outcome | Flag reason | Gold issues | Predicted |
|---|---|---|---|---|---|
| E01 | en | flagged | could not translate | signage | signage |
| E02 | en | flagged | could not translate | - | - |
| E03 | en | flagged | could not translate | - | - |
| E04 | en | flagged | could not translate | facilities | facilities |
| E05 | en | flagged | could not translate | safety | safety |
| E06 | en | flagged | could not translate | coffee_sales | coffee_sales |
| E07 | en | flagged | could not translate | - | - |
| E08 | en | flagged | could not translate | reply_time | - |
| E09 | en | flagged | could not translate | tour | tour |
| E10 | en | flagged | could not translate | payment | - |
| E11 | en | flagged | could not translate | - | - |
| E12 | en | flagged | could not translate | price | price |
| E13 | en | flagged | could not translate | language | language |
| E14 | en | flagged | could not translate | access_road | access_road |
| E15 | en | flagged | could not translate | - | - |
| E16 | en | flagged | could not translate | - | - |
| E17 | en | flagged | could not translate | facilities | facilities |
| E18 | en | flagged | could not translate | signage | signage |
| E19 | en | flagged | could not translate | signage | signage |
| E20 | en | flagged | could not translate | booking | booking |
| E21 | en | flagged | could not translate | accessibility | - |
| E22 | en | flagged | could not translate | hospitality | hospitality |
| E23 | en | flagged | could not translate | - | - |
| E24 | en | flagged | could not translate | tour | - |
| E25 | en | flagged | could not translate | coffee_sales | - |
| E26 | en | flagged | could not translate | - | - |
| E27 | en | flagged | language unclear | - | - |
| E28 | en | flagged | could not translate | - | - |
| E29 | en | flagged | could not translate | - | - |
| E30 | en | flagged | could not translate | - | - |
| M01 | de | correct |  | signage | signage |
| M02 | de | correct |  | signage | signage |
| M03 | de | correct |  | coffee_sales | coffee_sales |
| M04 | fr | correct |  | - | - |
| M05 | fr | correct |  | facilities | facilities |
| M06 | es | correct |  | safety | safety |
| M07 | id | correct |  | safety | safety |
| M08 | de | flagged | could not translate | - | - |
| M09 | fr | flagged | could not translate | language | - |
| M10 | es | flagged | could not translate | coffee_sales | - |
| M11 | nl | flagged | could not translate | access_road | - |
| M12 | ja | flagged | could not translate | - | - |
