# MILO benchmark (full suite, novel planner: reference)

| Planner | Known | Novel | Under faults | Steps | Sim time (s) | Replans |
|---|---|---|---|---|---|---|
| rule_based | 100% | 0% | 78% | 7.52 | 12.5 | 0.144 |
| react | 100% | 0% | 78% | 7.52 | 12.5 | 0.144 |
| behavior_tree | 100% | 0% | 78% | 5.63 | 9.88 | 0.144 |
| htn | 100% | 0% | 78% | 5.63 | 9.88 | 0.144 |
| novel | not run | 100% | not run | 5.25 | 9.38 | 0 |

## Recovery by fault kind

| Planner | blocked_path | out_of_reach | door_stuck | timeout | wrong_detection | missing_object |
|---|---|---|---|---|---|---|
| rule_based | 100% | 100% | 100% | 100% | 83% | 0% |
| react | 100% | 100% | 100% | 100% | 83% | 0% |
| behavior_tree | 100% | 100% | 100% | 100% | 83% | 0% |
| htn | 100% | 100% | 100% | 100% | 83% | 0% |
| novel | not run | not run | not run | not run | not run | not run |

## Harder tiers (memory, long missions, competing routes)

| Planner | memory | long | routes |
|---|---|---|---|
| rule_based | 100% | 100% | 0% |
| react | 100% | 100% | 0% |
| behavior_tree | 0% | 100% | 0% |
| htn | 0% | 100% | 0% |
| novel | not run | not run | not run |

## Ablations on the harder tiers (rule-based)

| Variant | memory | long | routes |
|---|---|---|---|
| full | 100% | 100% | 0% |
| no_memory | 0% | 100% | 0% |
| no_reflection | 100% | 100% | 0% |
| no_replanning | 100% | 100% | 0% |
| no_in_mission_recovery | 100% | 100% | 0% |

## Ablations

| Variant | Known + faults (rule-based) | Novel 2nd pass | Model calls |
|---|---|---|---|
| full | 81% | 100% | 0 |
| no_memory | 81% | – | – |
| no_reflection | 21% | – | – |
| no_replanning | 21% | – | – |
| no_in_mission_recovery | 57% | – | – |
| no_skills | – | 100% | 1 |

Ran in 20.4 s.
