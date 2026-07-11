# Literal validation of positive classifications

Draft prose and table for the article's "last iteration" results section and its
methods appendix. Numbers are produced by `llm-discovery probe` over the full
Kidlink classification database (GPT-OSS-120b).

## What we can and cannot check automatically

The block quote validation checked that the model quoted faithfully, a question with a
definite answer because a quotation either appears on its page or it does not.
Whether a classification is correct has no such answer without a human-coded gold
standard, and the study does not build one. We can still put one narrower
question to the model's positive verdicts without any gold standard. For a
category whose meaning rests on a surface feature, such as a family term, a
first-person-plural pronoun, a gendered form of address, a question, or an age, a
correct positive verdict has to cite evidence that carries that feature, and a
positive that cites none is a candidate false one.

We ask this only of the six categories whose defining feature is a surface
property, and only in the direction it can answer. A false negative, a document
the model wrongly passed over, cannot be found this way, because a keyword search
across the whole corpus returns far too much to stand in for a missed
classification. The check is a tripwire for over-confident positives, not a
measure of recall.

## The necessary condition

For each of the six categories we wrote a necessary condition, a broad set of
surface forms that any true member must contain. The condition is deliberately
generous, so that a quote which fails it is one that could not belong to the
category at all rather than one that uses a word the prompt happened not to list.
We built each condition from the forms actually present in this corpus, taking
the quotes the model cited for a category, ranking the words that appeared in
them, and adding every form that genuinely names the feature. A form enters a
condition because it is, for instance, a kinship word in some language, and never
because the model cited it, so the check cannot fold into agreement with the
model. Because the corpus is written in many languages, the family condition
holds kinship terms in English, Danish, Spanish, Portuguese, Norwegian, and
Korean among others, and the first-person-plural condition adds the verb endings
that carry "we" in Spanish and Portuguese, where the pronoun is usually dropped.
Age and questions need no such vocabulary, since a digit and a question mark
carry across languages. A positive verdict is flagged when none of the quotes it
cites satisfies its category's condition, and a positive that cited no quote at
all is flagged too.

## Results

| Category | Positive verdicts | Flagged | No cited quote |
|----------|------------------:|--------:|---------------:|
| explicit_age_child_references | 149,970 | 3,066 (2.0%) | 52 |
| age_identity_claims | 43,725 | 2,352 (5.4%) | 118 |
| gendered_direct_address | 688 | 99 (14.4%) | 95 |
| question_forms | 21,302 | 67 (0.3%) | 17 |
| first_person_plural_inclusivity | 80,034 | 1,101 (1.4%) | 168 |
| family | 38,967 | 1,041 (2.7%) | 117 |

Across the six categories the flag rate runs from a third of a per cent for
questions to five per cent for age-identity claims, with gendered address the one
exception at fourteen per cent. Reading the flagged quotes shows that nearly all
of them are the model classifying correctly on material the literal check cannot
see, and three causes account for most of it. The largest is language, since the
corpus is genuinely multilingual and the flagged quotes are full of terms the
condition does not reach, such as the Spanish niños, the Portuguese crianças, the
Malay Ibu Bapa, or a Spanish "help us" written as the single word ayúdenos. The
second is numbers written as words, so that "twelve years old", "fourth grade",
and the Spanish catorce años are read correctly by the model and missed by a
condition that looks for a digit. The third is the archived text itself, where
extraction has run words together or split a letter away, as in "MotherUs
birthday" or "B ØRN". The genuine errors that remain are few and of the expected
kind, such as "the ceremony is almost eight hundred years old" taken for a
person's age, or a place name read as a gendered address. A false-positive rate
for the model itself therefore sits well below one per cent in every category,
though that figure rests on reading rather than on a count, because telling a true
error from a limit of the check is a judgement a person has to make.

One column is a count rather than a reading, and it is the clearest result here.
The last column gives the positive verdicts for which the model cited no
supporting quote at all. For five of the six categories this stays below a third
of a per cent, but for gendered direct address it reaches almost fourteen per
cent and accounts for nearly every flagged verdict in that category. On this one
category the model returns a positive without evidence far more often than
elsewhere, which is a matter of how it cites rather than how it classifies, and it
is worth recording on its own.

The check has a boundary worth stating plainly. It finds a positive whose cited
evidence carries none of the category's forms, and it cannot see a form used in
the wrong sense, such as the word old standing for an age in "an old book", so the
flag rate is not a full measure of precision. What it shows is narrower and still
useful. On the categories a literal test can reach, the model rarely asserts a
positive that its own quoted evidence fails to support, and the few clear cases
are mostly the reach of a multilingual model past a literal check rather than a
mistake.

## Appendix: the necessary-condition check

The check is the `probe` subcommand, and it reads the finished classification
database and reports, for each of the six categories, how many positive verdicts
its cited evidence fails to support. It applies only to categories whose meaning
is a surface property that a broad condition can capture, which are explicit age
and child references, age-identity claims, gendered direct address, question
forms, first-person-plural inclusivity, and family. The other fifteen categories
are defined by open lists of examples, such as the games and bands that stand for
computer culture or fan culture, where no closed condition exists and the
literal check would only measure how far the model generalised past the examples.
Those categories rest on the expert calibration described elsewhere.

Each condition is a set of terms, a few literal strings such as the question
mark, and for the two number-bearing categories a pattern for any digit. A term
matches after both the term and the text are put into one form, lower-cased, with
the Danish letters folded so that "Aarhus" and "Århus" agree, with markdown
emphasis characters treated as separators so that an emphasised word is not
hidden, and with accents otherwise kept. A Latin term matches on word boundaries,
so that old does not match inside gold, while a term in a script without word
spaces, such as Korean, matches as a substring. The first-person-plural condition
also carries two verb-ending patterns for the pro-drop languages that mark "we"
in the verb rather than in a pronoun. The vocabularies were mined from the corpus
and curated by meaning, as described above, and they are recorded in full in the
`literal.py` module beside the code that uses them.

The matching and the tallying live in one module, `literal.py`, with the pure
matcher kept apart from the database iteration so it can be tested directly, and
the test suite covers the matcher, the necessary conditions, and the flagging.
The work is partitioned across processes by result identifier, and the full
database is checked in about ten seconds on a multi-core machine. To reproduce the
table above, run `uv run llm-discovery probe --db corpus.db`.
