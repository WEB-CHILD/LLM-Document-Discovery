# Block quote validation and pipeline appendix

Draft prose and table for the article's "last iteration" results section and its
methods appendix. Numbers are produced by `llm-discovery verify` over the full
Kidlink classification database (GPT-OSS-120b, 1,633,180 extracted quotations).

## Validation results (block quote validation)

The model was instructed to extract text exactly as it appeared and to make no
judgement about its meaning. This lets us check the result automatically, because a
faithful quotation must appear in the document it was taken from. We tested all
1,633,180 quotations the model produced for the Kidlink corpus. Allowing for
differences of whitespace and markdown, 99.3 per cent of them were found in their
source document. We then looked more closely at the rest. Once we stripped away all
remaining formatting and encoding, including markdown, accents, letter spacing, and
punctuation, only 231 quotations, or 0.014 per cent of the total, matched nothing on
the page. Almost none of these were invented. For instance, in a handful of cases
the model described the document instead of quoting it, returned the category's own
list of search words as if it were a quotation, or filled in a template such as "I
am ___ years old". Most of the rest were encoding artefacts, such as a missing space
in "2001Kidlink" or a dropped accent. When the model reports a match, the quoted
evidence is genuinely on the page in all but about one case in seven thousand.

GPT-OSS-120b is a mid-sized, open-weight model, and we ran it on university hardware
because the ethics protocol does not allow the corpus to be sent to a commercial
service. A stronger model reached over the internet would most likely remove even
this small residue, but only by moving the children's data off the university's own
machines, which the protocol does not permit. For our purposes a fabrication rate of
about one in seven thousand is a reasonable price for keeping that data under our own
control.

| Category | Quotations | Grounded | Genuine mismatch |
|----------|-----------:|---------:|-----------------:|
| explicit_age_child_references | 287,913 | 99.8% | 0.004% |
| corporate_register_markers | 113,008 | 96.1% | 0.045% |
| educational_register_markers | 181,834 | 99.8% | 0.022% |
| non_standard_spelling | 15,151 | 99.8% | 0.026% |
| syntactic_irregularities | 58,771 | 99.9% | 0.005% |
| topic_mixing_markers | 73,778 | 99.6% | 0.004% |
| age_identity_claims | 78,789 | 99.9% | 0.006% |
| gendered_direct_address | 627 | 99.7% | 0.159% |
| gendered_activities_objects | 35,136 | 99.9% | 0.011% |
| interactive_element_text | 76,546 | 99.9% | 0.003% |
| youth_slang_informality | 22,399 | 99.8% | 0.009% |
| question_forms | 51,438 | 99.9% | 0.008% |
| first_person_plural_inclusivity | 142,554 | 99.8% | 0.017% |
| family | 78,366 | 99.9% | 0.008% |
| directed_at_kids | 14,665 | 99.9% | 0.020% |
| fanculture | 10,703 | 99.8% | 0.000% |
| hobbies | 120,776 | 99.9% | 0.002% |
| computer_culture | 8,856 | 99.8% | 0.011% |
| conversations | 29,627 | 98.8% | 0.010% |
| governed_site | 204,980 | 97.9% | 0.023% |
| non_governed_site | 27,263 | 97.0% | 0.048% |
| **Total** | **1,633,180** | **99.3%** | **0.014%** |

Grounded is the share of quotations found in the source under the fuzzy match.
Genuine mismatch is the share still absent once all formatting is stripped. The
gap between them, largest for the boilerplate-heavy categories such as
`governed_site`, is presentation difference rather than fabrication, which is why
genuine mismatch stays near a few hundredths of a per cent across every category.

## Appendix: the document-discovery pipeline

### What it does

The pipeline takes a set of archived web pages and a set of researcher-defined
categories, and produces a database in which every page is classified against
every category, with the supporting text quoted. It runs as a sequence of
subcommands of `llm-discovery`, each writing its output to a shared SQLite
database.

1. **fetch.** Each page is downloaded from the Internet Archive Wayback Machine
   through its raw-content (`id_`) endpoint, packaged as a WARC file (the
   web-archive standard format), and converted from HTML to markdown with a
   `{timestamp}/{url}` header recording its provenance.
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

The pipeline records, for every match, the blockquote the model gave as evidence.
Because the model is told to extract verbatim text and to make no interpretive
judgement, that evidence can be audited automatically, since a faithful quotation
must occur in its source. The audit is the `verify` subcommand, and it compares each
quotation to its document in two passes. The first is a fuzzy match that tolerates
differences of whitespace and markdown (a rapidfuzz partial ratio), where a score of
at least 70 out of 100 counts as grounded and an exact substring scores 100. The
second pass looks only at quotations below that threshold. It reduces both the
quotation and the source to lowercase alphanumerics, with accents and Nordic letters
folded, and asks whether the quotation's content is still present. A quotation that
reappears differed from the source only in presentation, and one that does not is a
genuine mismatch. The matching and classification live in one module,
`blockquote_validation.py`, separate from the database iteration so they can be tested
directly, and the test suite covers the matching, the formatting-strip recovery, and
the per-category tally. To reproduce the table above, run
`uv run llm-discovery verify --db corpus.db`. The full corpus of 1.6 million
quotations is audited in under a minute on a multi-core machine.
