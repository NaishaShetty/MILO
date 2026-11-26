# MILO benchmark (full suite, novel planner: reference)

| Planner | Known | Novel | Under faults | Steps | Sim time (s) | Replans |
|---|---|---|---|---|---|---|
| react | 100% | 0% | 80% | 7.39 | 10.66 | 0.124 |

ReAct model: qwen2.5:7b via Ollama. On 99 of 179 cases ReAct handed at least one plan to the rule-based planner (119 plans in all). Counting only cases the model planned on its own, known + novel success is 43%.

## Recovery by fault kind

| Planner | blocked_path | out_of_reach | door_stuck | timeout | wrong_detection | missing_object |
|---|---|---|---|---|---|---|
| react | 100% | 100% | 100% | 100% | 96% | 0% |

## Harder tiers (memory, long missions, competing routes)

| Planner | memory | memory_synonyms | long | routes |
|---|---|---|---|---|
| react | 75% | 50% | 100% | 75% |

Ran in 8693.8 s.
