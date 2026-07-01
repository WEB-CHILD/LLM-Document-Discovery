-- Queries that reproduce every number in corpus-and-classification-profile.md.
-- Run against the published Kidlink database, for example:
--   sqlite3 corpus_kidlink.db ".read docs/corpus-profile-queries.sql"
-- All output is aggregate: no page text and no quotation is selected.

-- Scale -----------------------------------------------------------------------
SELECT 'archived pages (unsplit)'   AS metric, COUNT(*) AS value FROM result WHERE part_number IS NULL
UNION ALL SELECT 'split parts',          COUNT(*) FROM result WHERE part_number IS NOT NULL
UNION ALL SELECT 'classified units',     COUNT(*) FROM result
UNION ALL SELECT 'excluded files',       COUNT(*) FROM excluded_file
UNION ALL SELECT 'categories',           COUNT(*) FROM category
UNION ALL SELECT 'verdicts',             COUNT(*) FROM result_category
UNION ALL SELECT 'quotations',           COUNT(*) FROM result_category_blockquote;

-- Overall verdict distribution ------------------------------------------------
SELECT match, COUNT(*) AS n,
       ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM result_category), 1) AS pct
FROM result_category GROUP BY match;

-- Verdicts per category, ordered by how often the category was positive --------
SELECT c.category_name,
       SUM(rc.match = 'yes')   AS yes,
       SUM(rc.match = 'maybe') AS maybe,
       SUM(rc.match = 'no')    AS no,
       ROUND(100.0 * SUM(rc.match = 'yes') / COUNT(*), 1) AS yes_rate
FROM result_category rc JOIN category c ON rc.category_id = c.category_id
GROUP BY c.category_id ORDER BY yes DESC;

-- Positive categories per page (histogram) ------------------------------------
SELECT yes_n AS categories_matched, COUNT(*) AS pages FROM (
  SELECT result_id, SUM(match = 'yes') AS yes_n
  FROM result_category GROUP BY result_id
) GROUP BY yes_n ORDER BY yes_n;

-- Quotations per positive verdict ---------------------------------------------
SELECT ROUND(1.0 * (SELECT COUNT(*) FROM result_category_blockquote)
            / (SELECT COUNT(*) FROM result_category WHERE match IN ('yes','maybe')), 2)
       AS quotes_per_positive;

-- Reasoning-trace length by verdict -------------------------------------------
SELECT match, COUNT(*) AS n, ROUND(AVG(LENGTH(reasoning_trace)), 0) AS avg_chars
FROM result_category GROUP BY match;

-- Reasoning-trace length: positives with vs without a cited quote -------------
SELECT CASE WHEN EXISTS (
           SELECT 1 FROM result_category_blockquote b
           WHERE b.result_id = rc.result_id AND b.category_id = rc.category_id
       ) THEN 'has_quote' ELSE 'no_quote' END AS cited,
       COUNT(*) AS n, ROUND(AVG(LENGTH(rc.reasoning_trace)), 0) AS avg_chars
FROM result_category rc WHERE rc.match IN ('yes','maybe') GROUP BY cited;

-- Category co-occurrence with lift over independence ---------------------------
-- co = pages both marked 'yes'; lift = co * N / (yes_a * yes_b).
WITH y AS (
  SELECT category_id, COUNT(*) AS yes FROM result_category WHERE match = 'yes' GROUP BY category_id
), n AS (SELECT COUNT(DISTINCT result_id) AS docs FROM result_category),
pair AS (
  SELECT a.category_id AS a, b.category_id AS b, COUNT(*) AS co
  FROM result_category a JOIN result_category b
    ON a.result_id = b.result_id AND a.category_id < b.category_id
  WHERE a.match = 'yes' AND b.match = 'yes'
  GROUP BY a.category_id, b.category_id
)
SELECT ca.category_name AS cat_a, cb.category_name AS cat_b, p.co,
       ROUND(p.co * (SELECT docs FROM n) * 1.0 / (ya.yes * yb.yes), 2) AS lift
FROM pair p
JOIN y ya ON ya.category_id = p.a
JOIN y yb ON yb.category_id = p.b
JOIN category ca ON ca.category_id = p.a
JOIN category cb ON cb.category_id = p.b
WHERE p.co >= 2000
ORDER BY lift DESC;

-- Consistency: pages marked 'yes' on both opposed governance categories --------
SELECT COUNT(*) AS both_governed_and_non_governed FROM (
  SELECT rc.result_id FROM result_category rc JOIN category c ON rc.category_id = c.category_id
  WHERE c.category_name = 'governed_site' AND rc.match = 'yes'
  INTERSECT
  SELECT rc.result_id FROM result_category rc JOIN category c ON rc.category_id = c.category_id
  WHERE c.category_name = 'non_governed_site' AND rc.match = 'yes'
);
