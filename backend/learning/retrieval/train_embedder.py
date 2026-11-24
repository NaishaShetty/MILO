"""
train_embedder.py (backend/learning/retrieval)

Contrastive fine-tuning of the small sentence embedder (BGE-small, the model in
`models/sentence_embedder`) on MILO's memory-retrieval pairs:

    cd backend
    python -m learning.retrieval.train_embedder --db-dir data/episodes --out artifacts/memory_embedder

For every TRAIN query the positive is one of its relevant memories and the
negatives are (a) the other items in the batch and (b) a hard negative: a memory
of the same kind/job about a different object. Loss = InfoNCE (temperature 0.05),
mean pooling + L2 norm -- identical to `LearnedEmbedder` at serving time.
Validation recall@5 picks the best epoch. Nothing from validation/test scenes or
the held-out object classes is used for training.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import torch

from learning.retrieval.benchmark import Bench, build, metrics

BASE = "../models/sentence_embedder"


def _embed(
    model, tok, texts: List[str], device, grad: bool = True, max_length: int = 64
):
    enc = tok(
        texts, padding=True, truncation=True, max_length=max_length, return_tensors="pt"
    ).to(device)
    ctx = torch.enable_grad() if grad else torch.no_grad()
    with ctx:
        hidden = model(**enc).last_hidden_state
        mask = enc["attention_mask"].unsqueeze(-1).float()
        return torch.nn.functional.normalize(
            (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9), dim=1
        )


def rank_with(model, tok, bench: Bench, split: str, device) -> List[List[int]]:
    mems = bench.corpus[split]
    vecs = torch.cat(
        [
            _embed(model, tok, [m.text for m in mems[i : i + 256]], device, grad=False)
            for i in range(0, len(mems), 256)
        ]
    )
    ids = [m.mem_id for m in mems]
    out = []
    qs = bench.queries[split]
    for i in range(0, len(qs), 256):
        qv = _embed(model, tok, [q.text for q in qs[i : i + 256]], device, grad=False)
        top = (qv @ vecs.T).topk(min(10, len(ids)), dim=1).indices.cpu().tolist()
        out += [[ids[j] for j in row] for row in top]
    return out


def train(
    db_dir: Path,
    out: Path,
    epochs: int = 4,
    batch: int = 64,
    lr: float = 2e-5,
    seed: int = 0,
    base: str = BASE,
) -> Dict:
    from transformers import AutoModel, AutoTokenizer

    random.seed(seed)
    torch.manual_seed(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    bench = build(db_dir, seed=seed, per_split_queries=4000)
    tok = AutoTokenizer.from_pretrained(base)
    model = AutoModel.from_pretrained(base).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    corpus = {m.mem_id: m for m in bench.corpus["train"]}
    by_kind_obj: Dict[str, List] = {}
    for m in bench.corpus["train"]:
        by_kind_obj.setdefault(m.kind, []).append(m)
    pairs: List[Tuple[Any, List[Any]]] = []
    for q in bench.queries["train"]:
        pos = [corpus[i] for i in q.relevant if i in corpus]
        if pos:
            pairs.append((q, pos))
    best_recall = -1.0
    history = []
    for epoch in range(epochs):
        model.train()
        random.shuffle(pairs)
        for i in range(0, len(pairs), batch):
            chunk = pairs[i : i + batch]
            qs = [q.text for q, _ in chunk]
            positives = [random.choice(p) for _, p in chunk]
            hard: List[Any] = []
            for (q, _), pos in zip(chunk, positives):
                others = [m for m in by_kind_obj[pos.kind] if m.obj != q.obj]
                hard.append(random.choice(others) if others else pos)
            qv = _embed(model, tok, qs, device)
            dv = _embed(
                model, tok, [m.text for m in positives] + [m.text for m in hard], device
            )
            logits = (qv @ dv.T) / 0.05
            # Same-object items elsewhere in the batch are not negatives.
            same = torch.tensor(
                [
                    [
                        (
                            1.0
                            if j < len(chunk) and positives[j].obj == q.obj and j != k
                            else 0.0
                        )
                        for j in range(dv.shape[0])
                    ]
                    for k, (q, _) in enumerate(chunk)
                ],
                device=device,
            )
            logits = logits.masked_fill(same.bool(), -1e4)
            loss = torch.nn.functional.cross_entropy(
                logits, torch.arange(len(chunk), device=device)
            )
            opt.zero_grad()
            loss.backward()
            opt.step()
        model.eval()
        val = metrics(rank_with(model, tok, bench, "val", device), bench.queries["val"])
        history.append(
            {
                "epoch": epoch + 1,
                "loss": float(loss),
                **{k: round(v, 4) for k, v in val.items()},
            }
        )
        if val["recall@5"] > best_recall:
            best_recall = val["recall@5"]
            out.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(out)
            tok.save_pretrained(out)
    (out / "train_report.json").write_text(
        json.dumps(
            {"base": base, "history": history, "best_val_recall@5": best_recall},
            indent=2,
        )
    )
    return {"history": history, "best_val_recall@5": best_recall}


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db-dir", type=Path, default=Path("data/episodes"))
    parser.add_argument("--out", type=Path, default=Path("artifacts/memory_embedder"))
    parser.add_argument("--epochs", type=int, default=4)
    args = parser.parse_args(argv)
    print(json.dumps(train(args.db_dir, args.out, args.epochs), indent=2))


if __name__ == "__main__":
    main()
