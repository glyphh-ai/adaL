"""
Recall benchmark runner — see PROTOCOL.md.

Ranks the corpus's fact sentences for every query under three scorers
(lexical = Ada's shipped score, embedding = MiniLM, hybrid = RRF) and
reports hit@1 / hit@3 / MRR per query type, plus negative false-
injection. Frozen corpus → deterministic.

    PYTHONPATH=. .venv-bench/bin/python benchmark/recall/run_recall.py
"""

import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
CORPUS = HERE / "corpus.json"
OUT = HERE / "results"

# Ada's real tokenizer + lexical formula, so "lexical" == shipped recall.
from ada.memory.thought_space import _tokenize

# universal-slot fill per fact type (deterministic, no LLM) so the
# lexical arm sees exactly the slot tokens real recall would.
def _universal(name, ftype, value):
    if ftype == "residence":
        return {"entity": {"name": name}, "spatial": {"location": value}}
    if ftype == "color":
        return {"entity": {"name": name}, "perceptual": {"color": value}}
    pred = {"job": "works_as", "employer": "employed_by",
            "hobby": "hobby", "vehicle": "drives"}[ftype]
    return {"entity": {"name": name},
            "relational": {"subject": name, "predicate": pred, "object": value}}


def _slot_tokens(u):
    toks = set()
    for roles in u.values():
        for v in roles.values():
            toks |= set(_tokenize(str(v)))
    return toks


def _set_cosine(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / ((len(a) * len(b)) ** 0.5)


def lexical_score(q_tokens, content_tokens, all_tokens, slot_tokens):
    """Exactly score_thought's positive-path math (no struct bonus —
    these queries carry no enriched triple)."""
    token_sim = max(_set_cosine(q_tokens, content_tokens),
                    _set_cosine(q_tokens, all_tokens))
    slot_sim = (len(q_tokens & slot_tokens) / len(q_tokens)) if q_tokens else 0.0
    return token_sim * 0.5 + slot_sim * 0.2


def rrf(rank_a, rank_b, k=60):
    return 1.0 / (k + rank_a) + 1.0 / (k + rank_b)


def run_seed(seed_data, model):
    facts = seed_data["facts"]
    ids = [f["id"] for f in facts]
    id_index = {fid: i for i, fid in enumerate(ids)}
    sentences = [f["sentence"] for f in facts]

    # precompute lexical token sets
    content_toks, all_toks, slot_toks = [], [], []
    for f in facts:
        ct = set(_tokenize(f["sentence"]))
        sl = _slot_tokens(_universal(f["name"], f["fact_type"], f["value"]))
        content_toks.append(ct)
        slot_toks.append(sl)
        all_toks.append(ct | sl)

    # precompute embeddings for all facts
    emb = model.encode(sentences, normalize_embeddings=True,
                       show_progress_bar=False)

    # batch-encode queries
    queries = seed_data["queries"]
    q_emb = model.encode([q["query"] for q in queries],
                         normalize_embeddings=True, show_progress_bar=False)

    rows = []
    for qi, q in enumerate(queries):
        qt = set(_tokenize(q["query"]))
        lex = np.array([lexical_score(qt, content_toks[i], all_toks[i],
                                      slot_toks[i]) for i in range(len(facts))])
        embs = emb @ q_emb[qi]
        # ranks (1 = best) for RRF
        lex_rank = (-lex).argsort().argsort() + 1
        emb_rank = (-embs).argsort().argsort() + 1
        hyb = np.array([rrf(lex_rank[i], emb_rank[i]) for i in range(len(facts))])

        out = {"qtype": q["qtype"], "target": q["target_id"]}
        for name, scores in (("lexical", lex), ("embedding", embs),
                             ("hybrid", hyb)):
            order = (-scores).argsort()
            out[name] = {"top1_score": float(scores[order[0]])}
            if q["target_id"] is not None:
                tgt = id_index[q["target_id"]]
                rank = int(np.where(order == tgt)[0][0]) + 1
                out[name]["rank"] = rank
        rows.append(out)
    return rows


def calibrated_injection(pos_top1, neg_top1, keep=0.80):
    """τ = score that retains `keep` of correct positives; fraction of
    negatives at/above it = false-injection rate. Comparable across
    methods despite different score scales."""
    if not pos_top1 or not neg_top1:
        return None, None
    tau = float(np.quantile(np.array(pos_top1), 1 - keep))
    inj = float(np.mean(np.array(neg_top1) >= tau))
    return tau, inj


def main():
    OUT.mkdir(exist_ok=True)
    corpus = json.loads(CORPUS.read_text())
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    METHODS = ["lexical", "embedding", "hybrid"]
    TYPES = ["direct", "paraphrase", "conceptual", "contextual"]
    # per seed → per method → per type → list of (hit1,hit3,rr)
    agg = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    # correct-positive top1 scores + negative top1 scores, per method
    pos_top1 = defaultdict(lambda: defaultdict(list))
    neg_top1 = defaultdict(list)
    all_results = {}

    for seed, sd in corpus["seeds"].items():
        print(f"seed {seed}...", file=sys.stderr)
        rows = run_seed(sd, model)
        all_results[seed] = rows
        for r in rows:
            for m in METHODS:
                if r["qtype"] == "negative":
                    neg_top1[m].append(r[m]["top1_score"])
                    continue
                rank = r[m]["rank"]
                agg[seed][m][r["qtype"]].append(
                    (1.0 if rank == 1 else 0.0,
                     1.0 if rank <= 3 else 0.0, 1.0 / rank))
                if rank == 1:
                    pos_top1[m][seed].append(r[m]["top1_score"])

    (OUT / "results.json").write_text(json.dumps(all_results))

    def mean_over_seeds(m, qtype, idx):
        per_seed = []
        for seed in corpus["seeds"]:
            vals = [t[idx] for t in agg[seed][m][qtype]]
            if vals:
                per_seed.append(st.mean(vals) * 100)
        return (st.mean(per_seed), st.stdev(per_seed) if len(per_seed) > 1 else 0.0)

    print("\n=== hit@1 / hit@3 / MRR  (mean over 5 seeds, %) ===\n")
    hdr = f"{'type':12} " + "  ".join(f"{m:>22}" for m in METHODS)
    print(hdr)
    for qtype in TYPES:
        cells = []
        for m in METHODS:
            h1, _ = mean_over_seeds(m, qtype, 0)
            h3, _ = mean_over_seeds(m, qtype, 1)
            mrr, _ = mean_over_seeds(m, qtype, 2)
            cells.append(f"{h1:5.1f}/{h3:5.1f}/{mrr*1:5.1f}".rjust(22))
        print(f"{qtype:12} " + "  ".join(cells))

    # fuzzy average (paraphrase+conceptual+contextual), hit@3
    print("\n=== fuzzy-set hit@3 (paraphrase+conceptual+contextual) ===")
    for m in METHODS:
        vals = []
        for qtype in ("paraphrase", "conceptual", "contextual"):
            vals.append(mean_over_seeds(m, qtype, 1)[0])
        print(f"  {m:12} {st.mean(vals):5.1f}")

    print("\n=== negative false-injection (τ keeps 80% of correct top-1) ===")
    for m in METHODS:
        allpos = [s for seed in pos_top1[m].values() for s in seed]
        tau, inj = calibrated_injection(allpos, neg_top1[m])
        if tau is not None:
            print(f"  {m:12} τ={tau:.3f}  inject {inj*100:5.1f}%  "
                  f"(neg median {np.median(neg_top1[m]):.3f})")


if __name__ == "__main__":
    sys.exit(main())
