# Block quote validation and pipeline appendix

Draft prose and table for the article's "last iteration" results section and its
methods appendix. Numbers are produced by `llm-discovery verify` over the full
Kidlink classification database (GPT-OSS-120b, 1,633,180 extracted quotations).

## Validation results (block quote validation)

The model was instructed to extract text exactly as it appeared and to make no
judgement about its meaning. This lets us check the result automatically, because a
faithful quotation must appear in the document it was taken from. We tested all
1,633,180 quotations the model produced for the Kidlink corpus. The first pass
grounded 1,631,694 quotations, or 99.909 per cent. This total contains 1,455,041
exact substrings, or 89.09 per cent, and 176,653 fuzzy matches at the threshold of
70, or 10.82 per cent.

The formatting-stripped pass recovered another 1,318 quotations. A contiguous
skeleton appeared in the raw source for 245 quotations and in the link-stripped
source for 43 quotations. The remaining 1,030 met the 90 per cent word-overlap
condition alone.

The word-overlap result is weakly grounded and remains flagged. An eyes-on
stratified reading of 45 of the 1,030 quotations found 25 presentation-only
differences. It also found 16 verbatim segments spliced with unmarked omissions
and four recompositions. The substance-affected share was 44 per cent, with a 95
per cent interval of 31–59 per cent.

The supported result therefore has three parts. The first pass grounds 1,631,694
quotations, or 99.909 per cent. Formatting removal demonstrates that a further
288 quotations are contiguous. The validation does not defend 1,198 quotations,
or 0.073 per cent. This last group contains the 1,030 word-overlap-only results
and 168 quotations that matched nothing. The 168 unmatched quotations make up
0.0103 per cent of the corpus, or about one in 9,700.

The smallest category, `gendered_direct_address`, contained 627 quotations. One
was a genuine mismatch, or 0.159 per cent. The full per-category results from
the 2026-07-12 rerun (`llm-discovery verify --db corpus.db`, dual-form matching,
threshold 70):

| Category | Quotations | Grounded | Genuine mismatch |
|----------|-----------:|---------:|-----------------:|
| explicit_age_child_references | 287,913 | 99.95% | 0.004% |
| corporate_register_markers | 113,008 | 99.97% | 0.022% |
| educational_register_markers | 181,834 | 99.94% | 0.022% |
| non_standard_spelling | 15,151 | 99.92% | 0.026% |
| syntactic_irregularities | 58,771 | 99.98% | 0.002% |
| topic_mixing_markers | 73,778 | 99.82% | 0.004% |
| age_identity_claims | 78,789 | 99.96% | 0.006% |
| gendered_direct_address | 627 | 99.84% | 0.159% |
| gendered_activities_objects | 35,136 | 99.97% | 0.011% |
| interactive_element_text | 76,546 | 99.98% | 0.003% |
| youth_slang_informality | 22,399 | 99.91% | 0.009% |
| question_forms | 51,438 | 99.97% | 0.004% |
| first_person_plural_inclusivity | 142,554 | 99.96% | 0.011% |
| family | 78,366 | 99.94% | 0.008% |
| directed_at_kids | 14,665 | 99.97% | 0.020% |
| fanculture | 10,703 | 99.83% | 0.000% |
| hobbies | 120,776 | 99.93% | 0.002% |
| computer_culture | 8,856 | 99.86% | 0.011% |
| conversations | 29,627 | 99.44% | 0.010% |
| governed_site | 204,980 | 99.76% | 0.013% |
| non_governed_site | 27,263 | 99.77% | 0.044% |
| **Total** | **1,633,180** | **99.91%** | **0.010%** |

The stored evidence also contains a generation-side artifact. In 69 blockquotes,
the literal token `<|constrain|>` appears in place of `http` in a URL.

## Appendix: the document-discovery pipeline

### What it does

The pipeline takes a set of archived web pages and a set of researcher-defined
categories, and produces a database in which every page is classified against
every category, with the supporting text quoted. It runs as a sequence of
subcommands of `llm-discovery`, each writing its output to a shared SQLite
database.

1. **fetch.** Each new page is downloaded from the Internet Archive Wayback
   Machine through its raw-content (`id_`) endpoint. The default path preserves
   the response as a WARC file and converts its HTML payload to markdown with a
   `{timestamp}/{url}` header. The Kidlink corpus used for the reported results
   was converted to markdown by an upstream process before this repository
   existed. It did not pass through this fetch pipeline.
2. **prep-db.** A SQLite database is created from `schema.sql`. The 21 category
   definitions are loaded from `prompts/*.yaml`, and the documents are loaded with
   change detection by SHA-256. Any document longer than 80,000 characters is split
   at paragraph boundaries with a 500-character overlap so that each part fits the
   model's context window.
3. **preflight.** Every document is checked for usable text. Binary files are
   rejected by their magic bytes, documents below a minimum length are dropped, and
   pages with a low proportion of printable characters are excluded before any
   model time is spent on them.
4. **process.** This is the classification stage. A reader thread streams
   document-category pairs from the database into a bounded work queue, and a pool
   of worker threads, sized to saturate the GPU's batch capacity, sends each pair to
   a locally served model over an OpenAI-compatible HTTP interface. For each pair the
   model returns a yes, maybe, or no verdict, a short reasoning trace, and any
   verbatim blockquotes. Each result is written to its own JSON file using a
   temporary-file-then-rename, so any result that reaches disk survives an abrupt
   shutdown. All inference runs at temperature zero for reproducibility.
5. **import-results.** The JSON result files are read into the database
   idempotently, so a re-run after interruption never duplicates a result.
6. **verify.** The block quote validation, checking each extracted blockquote against the
   document it came from. It is described at the end of this appendix.

### Running it on a supercomputer

The model is self-hosted because the ethics protocol does not allow the corpus to
leave university infrastructure. The classification stage runs inside a container,
built on the vLLM image, that serves GPT-OSS-120b across two NVIDIA H100 GPUs in a
tensor-parallel configuration. The work for this article ran on the UCloud
interactive system at the University of Southern Denmark, and the same code targets
the NCI Gadi system, which provides Singularity rather than Apptainer.

Setting up an HPC environment is done once. `build` produces the container image,
`download-model` fetches the model weights to the local cache, and `init` stages the
container and weights to the HPC scratch area and submits a short job that confirms
the model starts and answers. Processing a corpus is then a per-run cycle. After
`fetch`, the `deploy` command assembles the data directory, uploads it, and submits
the classification job, or `run` performs the whole sequence end to end. `status`
follows the running job and `retrieve` pulls the finished database back.

The design is shaped by how an interactive allocation behaves. On UCloud an
allocation starts with a one-hour wall-clock limit that has to be extended by hand
while the machine runs, and if it lapses the node is killed with no graceful signal.
The pipeline is therefore built to resume from the results already on disk, picking
up the unprocessed pairs on the next allocation. An earlier design wrote results
through SQLite's write-ahead log synchronised with Syncthing, which corrupted the
database because that log assumes a single host holds the lock. Results are now
written as individual JSON files, which replicate safely, and imported to SQLite
afterwards.

### Verifying extracted quotations

The pipeline records the blockquote that supports each match. The `verify`
subcommand compares every quotation with its source in two passes. Every
comparison uses both the raw source and a variant produced by `strip_links`, and
the better reading wins.

Pass 1 normalises whitespace and markdown escapes. It checks for an exact
substring before calling `rapidfuzz.fuzz.partial_ratio`. A score of at least 70
counts as grounded. A quotation containing the explicit `[...]` omission marker
is split into fragments, and every non-empty fragment must meet the threshold.

Pass 2 applies only below that threshold. The `skeleton` function folds case,
accents, and Nordic letters before retaining lowercase alphanumerics. The quote
recovers when its raw skeleton is a substring of the raw source skeleton or its
link-stripped skeleton is a substring of the link-stripped source skeleton. It
also recovers when at least 90 per cent of its word tokens appear in the source.
The first two branches demonstrate contiguous source text after formatting is
removed. The word-overlap branch is a weakly grounded flag because it also
accepts spliced and recomposed text.

The matching and classification live in `blockquote_validation.py`. Database
iteration is kept separate so the pure functions can be tested directly. The
test suite covers matching, formatting-strip recovery, and per-category tallying.
Run `uv run llm-discovery verify --db corpus.db` to reproduce the audit.
