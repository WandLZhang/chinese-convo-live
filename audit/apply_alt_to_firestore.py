"""
STAGED writer — precompute the colloquial-alternative decision into Firestore.

Adds ONE field `alt` to the vocab docs that have an attested alternative (the 45 R2/R3 words
from the audit). `alt` = the colloquial word to use in the question; ABSENT means "use the word
directly" (the 98% rule-1/rule-4 case). The `cantonese` sentence field is NOT touched here.

This makes runtime a pure Firestore read + LLM generate — no rule-sifting, no per-request RAG.

  DRY RUN (default, writes nothing):  python audit/apply_alt_to_firestore.py
  WRITE:                              python audit/apply_alt_to_firestore.py --go

Reversible: audit/backup_cantonese_current.jsonl holds the pre-change snapshot; `alt` is additive
(delete the field to fully revert).
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "bench"))
import bench_colloquial as B

NL = chr(10)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually write (default is dry-run)")
    args = ap.parse_args()

    alt = {}
    with open(os.path.join(HERE, "alt_map.jsonl"), encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("alt"):
                alt[d["word"]] = d["alt"]
    mode = "WRITE" if args.go else "DRY-RUN"
    print(f"{len(alt)} words have an attested alt. Mode: {mode}  (cantonese sentences untouched)")

    coll = B._db.collection("vocabulary")
    batch = B._db.batch()
    pending = 0
    matched = 0
    for d in coll.stream():
        w = d.to_dict().get("simplified")
        if w in alt:
            matched += 1
            print(f"  {w:10} -> alt={alt[w]}")
            if args.go:
                batch.update(d.reference, {"alt": alt[w]})
                pending += 1
                if pending >= 400:
                    batch.commit()
                    batch = B._db.batch()
                    pending = 0
    if args.go and pending:
        batch.commit()
    print(f"{NL}{'WROTE' if args.go else 'WOULD WRITE'} `alt` on {matched} docs. "
          f"Absent `alt` = use word directly ({'unchanged' if args.go else 'no change made'}).")


if __name__ == "__main__":
    main()
