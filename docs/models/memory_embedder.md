# Model card: memory embedder (Phase D)

**What it is.** `BGE-small` (384-d) contrastively fine-tuned (InfoNCE, temperature 0.05, in-batch + hard negatives, same-object masking) so that a task query lands near the memories that help with it. Served as embedding provider `learned`; an optional gradient-boosted reranker can re-order the top candidates.

**Flags (all off by default; safe fallback = hashing embedder / unchanged order)**

| Variable | Meaning |
|---|---|
| `MEMORY_EMBEDDING_PROVIDER=learned` | use the fine-tuned embedder |
| `MEMORY_LEARNED_EMBEDDER_DIR` | model dir (default `artifacts/memory_embedder`); any load failure logs a warning and falls back to `HashingEmbedder` |
| `MEMORY_LEARNED_RERANKER=1`, `MEMORY_RERANKER_PATH` | apply the reranker; failure leaves the order untouched |

Switching embedder re-embeds existing memories automatically when the vector store is empty (vectors of another dimension are otherwise skipped).

**Data.** Phase A synthetic episode logs, turned into a per-split corpus (facts / moments / oopses) using the real production memory text. Splits are by scene; the objects `plate`, `tomato`, `bottle` are held out of train/val entirely.

**Results** (held-out scenes, 1,200 queries over 553 memories; 210 queries on unseen objects)

| Method | recall@5 | recall@5 (unseen objects) |
|---|---|---|
| Hashing baseline | 0.606 | 0.751 |
| BGE-small off the shelf | 0.769 | 0.815 |
| Fine-tuned | 0.9997 | 0.998 |
| Fine-tuned + reranker | 0.9998 | – |

Latency (fine-tuned, GPU, real `RetrievalEngine`): 5,000 memories p50 5.8 ms / p95 10.2 ms; 50,000 memories p50 8.5 ms / p95 15.4 ms.

**Honest caveats**

- The benchmark is generated from synthetic logs with query templates that overlap the training templates, and "relevant" means "same object". A near-perfect score mostly shows the model learned that mapping; it is **not** evidence of that accuracy on real user phrasing.
- The reranker added **no measurable gain** (0.9997 → 0.9998); the embedder alone is already at the ceiling of this benchmark. It ships behind its flag only.
- **No mission-level effect.** 200 held-out-scene episodes with memory in the loop gave identical results for hashing and learned (success 0.72, 9.905 steps/mission, memory hint used 0.595). The planner's hint depends on the parsed object name, so both embedders surface the same fact. The retrieval gain does not currently translate into better missions.
- Recommendation: keep `hashing` as the default; use `learned` when queries are phrased more freely than the object name (synonyms), and re-evaluate on real memory logs before promoting it.

Reproduce: `make train-embedder eval-retrieval eval-retrieval-missions`.

## On the benchmark's memory tiers (2026-11-26)

On the memory tier (objects start out of view; only going where they usually are finds them) both embedders give 8/8. There the planner finds the place by the object's exact name, so the embedder isn't involved.

What changed: when nothing is remembered under the exact name, the planner now compares the object's name with the names of remembered places' subjects ("ceramic mug" vs "mug") using this embedder, and uses a place only if its name is clearly the closest: at least the embedder's minimum similarity (hashing 0.45, learned 0.60, as their scales differ) and 0.05 above the runner-up. Otherwise there is no hint, so MILO searches as before rather than going to a wrong place.

The thresholds were picked on a probe set of eight paraphrases ("coffee mug", "paperback novel", "water bottle", "dinner plate", "teacup", "cherry tomato", "spud", "hen's egg"). There, name similarity was 0.46-0.74 for hashing where a word is shared (0 for "paperback" and "spud"), and 0.67-0.92 for learned (0.43 for "spud"). The highest wrong pair was 0.26 for hashing and 0.55 for learned.

The benchmark's **memory_synonyms** tier uses eight different paraphrases ("ceramic mug", "hardcover", "flask", "paper cup", "serving plate", "plum tomato", "baked potato", "boiled egg"), fixed before measuring:

| Embedder | memory tier | memory_synonyms tier | Misses |
|---|---|---|---|
| hashing (default) | 8 / 8 | 6 / 8 | "hardcover", "flask": no shared word |
| learned (fine-tuned BGE-small) | 8 / 8 | 7 / 8 | "flask" |

So the learned embedder now changes mission success, by one mission in eight, on synonyms that share no word with the object. The gap is small partly because six of the eight held-out paraphrases contain the object's own word, which hashing can match. That list was not changed after seeing these results. Reproduce: `make benchmark` (the `learned_memory_embedder` ablation row runs when a trained embedder exists).

A first version of this fallback ranked candidates by their similarity to the whole query instead of by name. It let an unrelated memory ("refrigerator in the kitchen") steer the search for a mug, which an existing test caught; it was replaced before release.
