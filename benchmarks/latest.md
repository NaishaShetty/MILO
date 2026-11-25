# MILO benchmark (full suite, novel planner: reference)

| Planner | Known | Novel | Under faults | Steps | Sim time (s) | Replans |
|---|---|---|---|---|---|---|
| rule_based | 100% | 0% | 48% | 7.78 | 11.67 | 0.144 |
| react | 100% | 0% | 48% | 7.78 | 11.67 | 0.144 |
| behavior_tree | 100% | 0% | 48% | 5.58 | 9.05 | 0.144 |
| htn | 100% | 0% | 48% | 5.58 | 9.05 | 0.144 |
| novel | not run | 100% | not run | 5.25 | 9.38 | 0 |

## Recovery by fault kind

| Planner | blocked_path | out_of_reach | door_stuck | timeout | wrong_detection | missing_object |
|---|---|---|---|---|---|---|
| rule_based | 100% | 22% | 100% | 100% | 4% | 0% |
| react | 100% | 22% | 100% | 100% | 4% | 0% |
| behavior_tree | 100% | 22% | 100% | 100% | 4% | 0% |
| htn | 100% | 22% | 100% | 100% | 4% | 0% |
| novel | not run | not run | not run | not run | not run | not run |

## Ablations

| Variant | Known + faults (rule-based) | Novel 2nd pass | Model calls |
|---|---|---|---|
| full | 57% | 100% | 0 |
| no_memory | 57% | – | – |
| no_reflection | 21% | – | – |
| no_replanning | 21% | – | – |
| no_skills | – | 100% | 1 |

Ran in 8.8 s.
