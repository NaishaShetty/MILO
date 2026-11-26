# What's left (2026-11-26)

A short, current list. Long-term research directions are in [roadmap.md](roadmap.md#future-work); measured results are in the [README](../README.md).

## Needs your laptop's time

These are ready to run but take hours, so they weren't started for you. All are resumable.

```bash
make collect-thor       # 600 real AI2-THOR episodes, about 5-10 hours: run it overnight
make train-real         # after collect-thor: retrain the outcome predictor on real episodes
make benchmark-thor     # the benchmark in real AI2-THOR, about 1 hour per planner
```

Use `MILO_OLLAMA_KEEP_ALIVE=0` if a local model shares the GPU ([local_model.md](local_model.md)).

## Needs you

| What | Why it needs you | Then |
|---|---|---|
| Write `data/parser_test_human.jsonl` | It must be commands a person wrote, not generated ones | `make eval-parser` |
| Hugging Face dataset and Space refresh | Needs your login. Revoke the token pasted in chat first, then run `huggingface-cli login` yourself | Upload the new results (ReAct, prompt v3, memory red team) |
| A Claude result | No API credits; no number here comes from Claude | `python -m benchmark.run --provider claude` and `python -m novel.eval_novel --claude` (from `backend/`) |
| Voice in a real browser | Real speech recognition can't be checked in the test browser ([voice.md](voice.md), "Not verified") | Try a spoken command once in Chrome or Edge and note what happened |
| Public demo (Cloudflare Pages) | Needs your Cloudflare account, and a hosted backend: the frontend alone shows an offline app | `npm run build` in `frontend/`, deploy `dist/` |

## Open problems (measured, not solved)

- **Asking about ambiguous commands.** The local model asks on 2 of 8 ambiguous TEST commands, even with prompt v3; it usually guesses and plans. The plan approval step is the guard meanwhile ([novel_tasks.md](novel_tasks.md)).
- **Someone else telling MILO something directly** looks exactly like you changing your mind. Defending it needs speaker identity ([memory_trust.md](memory_trust.md)).
- **ReAct with a 7B model** plans only one- and two-step tasks on its own; everything longer falls back to rule-based ([benchmark.md](benchmark.md)).
- **The world model catches 0 of 4 route failures**; it has only seen synthetic episodes (`make train-real` is the next step).
- **Behaviour tree and HTN ignore memory**, so they score 0% on the memory tiers.
- **Rule-based runs more steps than behaviour tree and HTN** on the same first plans; the cause hasn't been traced.
- **Composing two learned skills** saves no model calls.
- **Nearly everything is measured in the synthetic home**, not real AI2-THOR. `make benchmark-thor` is the fix.

## Smaller items not done

- A "Record" button for saving a mission as a demo clip from the app.
- A browser test for voice with a fake microphone (Playwright fake media), and a short manual checklist for trying voice in a real browser.
- Scripts to fetch and publish trained model weights.
- A `ci-gate-demo` branch that shows the benchmark gate failing a deliberately broken change.
