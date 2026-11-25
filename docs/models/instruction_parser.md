# Model card: small instruction parser (Phase E)

**What it is.** A CPU-only parser with two scikit-learn parts: an intent classifier (word + character TF-IDF -> logistic regression over 13 goals) and a token tagger (object / target / other, from word-shape and neighbouring-word features, so unseen nouns are still tagged from context). It parses in about 1 ms and trains in seconds.

**Where it sits.** `InstructionInterpreter` runs help, question, preference and chain handling first. If a parser is supplied, it then tries it on the raw sentence and acts only when confident (confidence = lowest of the intent probability and the needed slot probabilities). Otherwise the single-task phrasebook and then the LLM run exactly as before. Answers are tagged `source: "learned"`.

| Variable | Meaning |
|---|---|
| `MILO_LEARNED_PARSER=1` | enable (default off) |
| `MILO_PARSER_DIR` | directory containing `parser.pkl` (default `artifacts/parser`) |
| `MILO_PARSER_THRESHOLD` | minimum confidence, default 0.7 |

A missing or unreadable model, a low-confidence parse, a missing required slot, or any exception all mean "no answer", so behaviour falls back to the phrasebook/LLM.

**Evaluation.** Trained on 6,000 synthetic instructions; tested on 1,500 *novel phrasings* (paraphrase templates never seen in training, plus object/place words never seen in training, plus typos/fillers). Gold labels come from the generating template, not from the rules.

| System | Coverage | Exact (goal + object + target) | Accuracy when answering |
|---|---|---|---|
| Rule phrasebook | 0.304 | 0.137 | 0.452 |
| Learned alone | 1.000 | 0.620 | 0.620 |
| Learned-first (conf >= 0.5), rules otherwise | 0.785 covered by learned | 0.647 | 0.825 |
| Learned-first (conf >= 0.7, the default) | 0.683 covered by learned | 0.573 | 0.838 |

Calibration: ECE of the exact-match confidence 0.058. Speed: 1.0 ms per parse. On phrasings seen in training the learned-first system is 99.9% exact, so enabling it does not regress them.

**Honest caveats**

- All data are templates written by us. The test phrasings are different from the training ones, but they are still our own idea of how people talk. The numbers say nothing about real users' language until it is measured on real transcripts.
- The rules' low score is partly by design: the test set is deliberately outside their phrasebook. They are also *overconfident* there (45% right when they answer, e.g. "get the candle over to the cabinet" is read as `fetch`).
- Weak goals on novel phrasing: `navigate_to` (0.03, often read as `deliver`), `pick_up` (0.21, often `fetch`), `deliver` (0.45), `store` (0.43). These get low confidence, so at the default threshold they are mostly sent on to the rules/LLM rather than acted on wrongly, but coverage there is poor. More diverse training phrasing would help.
- Objects and places are single words ("kitchen towel" is not handled), and colour/size attributes are not extracted.
- The learned parser sees one sentence; compound ("... and then ...") instructions are still handled by the rules.

Reproduce: `make eval-parser` (writes `artifacts/parser/parser.pkl` and `eval.json`).
