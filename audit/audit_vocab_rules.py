"""
Audit EVERY vocab word in Firestore against the locked colloquial-alternative rules.

Rules (priority, per spec) — evaluated ONLY against the word's OWN Words.hk entry:
  1. a yue: example uses W                      -> use W directly
  2. a zho:->yue: rephrase replaces W with X    -> use X
  3. (sim:X) present                            -> use X   (fires mainly for 書面語 words w/o self-example)
  4. none / no own entry                        -> use W directly (flagged)

Stored sentence and model knowledge are NOT inputs. One RAG retrieval per word.
Records the (label:書面語) marking too, since those are the words that actually need an alternative.
Writes JSONL incrementally (flush per row); prints distribution + rule-2/3 test-set candidates at end.

Run from anywhere: source bench/.venv/bin/activate && python audit/audit_vocab_rules.py [--limit N]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bench"))
import bench_colloquial as B  # reuse RAG client, firestore, OpenCC

NL = chr(10)
OUT = os.path.join(HERE, "vocab_rule_audit.jsonl")


def cands(w):
    t = B.conv.convert(w)
    return {w, t, t.replace("爲", "為"), t.replace("為", "爲")}


def own_entry(w):
    """The word's OWN Words.hk entry (headword == W), or None."""
    for c in B._retrieve(B.conv.convert(w), 15):
        first = c.text.split(NL)[0]
        if any((h + ":") in first for h in cands(w)):
            return c.text
    return None


def self_eg(w, t):
    """A yue: EXAMPLE (after <eg>) that uses W itself."""
    for seg in t.split("<eg>")[1:]:
        for ls in seg.split(NL):
            s = ls.strip()
            if s.startswith("yue:") and any(h in s for h in cands(w)):
                return True
    return False


def rephrase_alt(w, t):
    """zho: line contains W, the paired yue: example does NOT -> the yue phrasing is the colloquial swap."""
    if "zho:" not in t:
        return None
    parts = t.split(NL)
    for i, l in enumerate(parts):
        if l.strip().startswith("zho:") and any(h in l for h in cands(w)):
            for j in range(i + 1, min(i + 3, len(parts))):
                if parts[j].strip().startswith("yue:") and not any(h in parts[j] for h in cands(w)):
                    return parts[j].strip()[4:].split("(")[0].strip()[:40]
    return None


def sim_tags(t):
    return [seg.split(")")[0] for seg in t.split("(sim:")[1:]]


def classify(w):
    t = own_entry(w)
    if not t:
        return {"word": w, "rule": 4, "alt": None, "own": False, "syumin": False, "sim": [], "note": "no own entry"}
    syumin = "label:書面語" in t
    sims = sim_tags(t)
    se = self_eg(w, t)
    reph = rephrase_alt(w, t)
    if se:
        rule, alt = 1, None
    elif reph:
        rule, alt = 2, reph
    elif sims:
        rule, alt = 3, sims[0]
    else:
        rule, alt = 4, None
    return {"word": w, "rule": rule, "alt": alt, "own": True, "syumin": syumin, "sim": sims, "self_eg": se}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = all vocab")
    args = ap.parse_args()

    words, seen = [], set()
    for d in B._db.collection("vocabulary").stream():
        w = d.to_dict().get("simplified")
        if w and w not in seen:
            seen.add(w)
            words.append(w)
    if args.limit:
        words = words[: args.limit]
    print(f"auditing {len(words)} vocab words...", flush=True)

    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    r2, r3, syumin_sim = [], [], []
    with open(OUT, "w", encoding="utf-8") as f:
        for i, w in enumerate(words):
            try:
                row = classify(w)
            except Exception as e:  # noqa: BLE001
                row = {"word": w, "rule": 4, "error": str(e)[:120]}
            r = row.get("rule", 4)
            counts[r] = counts.get(r, 0) + 1
            if r == 2:
                r2.append((row["word"], row.get("alt")))
            if r == 3:
                r3.append((row["word"], row.get("alt")))
            if row.get("syumin") and row.get("sim"):
                syumin_sim.append((row["word"], row.get("sim")))
            f.write(json.dumps(row, ensure_ascii=False) + NL)
            f.flush()
            if (i + 1) % 25 == 0:
                print(f"  {i+1}/{len(words)}  R1={counts[1]} R2={counts[2]} R3={counts[3]} R4={counts[4]}", flush=True)

    n = max(len(words), 1)
    print(f"{NL}=== RULE DISTRIBUTION (n={len(words)}) ===")
    for r in (1, 2, 3, 4):
        print(f"  R{r}: {counts[r]}  ({100*counts[r]//n}%)")
    print(f"  ALTERNATIVE path (R2+R3): {counts[2]+counts[3]}  ({100*(counts[2]+counts[3])//n}%)")
    print(f"{NL}RULE-2 rephrase words [{len(r2)}]: {r2[:80]}")
    print(f"{NL}RULE-3 sim words [{len(r3)}]: {r3[:80]}")
    print(f"{NL}書面語 words WITH sim: [{len(syumin_sim)}]: {syumin_sim[:80]}")


if __name__ == "__main__":
    main()
