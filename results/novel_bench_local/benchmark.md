# MILO benchmark (full suite, novel planner: ollama)

| Planner | Known | Novel | Under faults | Steps | Sim time (s) | Replans |
|---|---|---|---|---|---|---|
| novel | 74% | 100% | 61% | 6.78 | 11.58 | 0.268 |

## Recovery by fault kind

| Planner | blocked_path | out_of_reach | door_stuck | timeout | wrong_detection | missing_object |
|---|---|---|---|---|---|---|
| novel | 74% | 74% | 100% | 74% | 74% | 0% |

## Harder tiers (memory, long missions, competing routes, impossible requests)

| Planner | memory | memory_synonyms | long | routes | impossible |
|---|---|---|---|---|---|
| novel | 0% | 0% | not run | 50% | 100% |

Ran in 620.9 s.
