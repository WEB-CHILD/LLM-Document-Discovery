"""Category co-occurrence: pairwise heatmap and top three-way combinations.

The heatmap shows lift, how much more (red) or less (blue) than chance two
categories are both marked 'yes' on a page. The three-way section counts the pages
where three categories all fire, ranked by count, with example document ids so the
combinations can be read and judged.
"""

import sqlite3
import sys
from collections import Counter
from itertools import combinations
from math import log2
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage

db = sys.argv[1]
out = Path(sys.argv[2])

SHORT = {
    "explicit_age_child_references": "age/child",
    "corporate_register_markers": "corporate",
    "educational_register_markers": "educational",
    "non_standard_spelling": "spelling",
    "syntactic_irregularities": "syntax",
    "topic_mixing_markers": "topic-mix",
    "age_identity_claims": "age-identity",
    "gendered_direct_address": "gendered-addr",
    "gendered_activities_objects": "gendered-act",
    "interactive_element_text": "interactive",
    "youth_slang_informality": "slang",
    "question_forms": "questions",
    "first_person_plural_inclusivity": "inclusive-we",
    "family": "family",
    "directed_at_kids": "directed-kids",
    "fanculture": "fanculture",
    "hobbies": "hobbies",
    "computer_culture": "computer",
    "conversations": "conversations",
    "governed_site": "governed",
    "non_governed_site": "non-governed",
}

conn = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
names = dict(conn.execute("SELECT category_id, category_name FROM category"))
doc_yes: dict[int, list[int]] = {}
for rid, cid in conn.execute(
    "SELECT result_id, category_id FROM result_category WHERE match='yes' ORDER BY result_id"
):
    doc_yes.setdefault(rid, []).append(cid)
n_docs = conn.execute("SELECT COUNT(DISTINCT result_id) FROM result_category").fetchone()[0]
conn.close()

cats = sorted(names)
idx = {c: i for i, c in enumerate(cats)}
yes = Counter()
pair = Counter()
triple = Counter()
triple_ex: dict[tuple, list[int]] = {}
for rid, cs in doc_yes.items():
    for c in cs:
        yes[c] += 1
    for a, b in combinations(sorted(cs), 2):
        pair[(a, b)] += 1
    for t in combinations(sorted(cs), 3):
        triple[t] += 1
        if len(triple_ex.setdefault(t, [])) < 6:
            triple_ex[t].append(rid)

# --- pairwise lift matrix ---
k = len(cats)
lift = np.full((k, k), np.nan)
for (a, b), c in pair.items():
    lg = log2((c / n_docs) / ((yes[a] / n_docs) * (yes[b] / n_docs)))
    lift[idx[a], idx[b]] = lift[idx[b], idx[a]] = lg

# cluster order using pairwise similarity (fill diagonal high, nan->0 for linkage)
sim = np.nan_to_num(lift, nan=0.0)
np.fill_diagonal(sim, np.nanmax(lift[~np.isnan(lift)]))
order = leaves_list(linkage(sim, method="average"))
labels = [SHORT[names[cats[i]]] for i in order]
M = lift[np.ix_(order, order)]

vmax = np.nanmax(np.abs(lift[~np.isnan(lift)]))
fig, ax = plt.subplots(figsize=(11, 9.5))
im = ax.imshow(M, cmap="RdBu_r", vmin=-vmax, vmax=vmax)
ax.set_xticks(range(k), labels, rotation=90, fontsize=8)
ax.set_yticks(range(k), labels, fontsize=8)
ax.set_title("Category co-occurrence (log2 lift over chance, 'yes' verdicts)", fontsize=11)
cbar = fig.colorbar(im, ax=ax, shrink=0.7)
cbar.set_label("under-represented  ←  chance  →  over-represented", fontsize=8)
fig.tight_layout()
fig.savefig(out, dpi=150)
print(f"wrote {out}")

# --- top three-way combinations ---
print("\n=== top 20 three-way category combinations (all three 'yes') ===")
print(f"{'pages':>7}  {'lift':>5}  categories | example result_ids")
for t, c in triple.most_common(20):
    a, b, d = t
    lg = (c * n_docs * n_docs) / (yes[a] * yes[b] * yes[d])
    trio = " + ".join(SHORT[names[x]] for x in t)
    ex = ",".join(str(r) for r in triple_ex[t][:6])
    print(f"{c:7,}  {lg:5.1f}  {trio} | {ex}")
