-- Boolean Index Database Schema
-- Normalized relational structure for children's web corpus analysis (1996-2005)

-- Source documents from corpus
-- For split documents: original has part_number=NULL, parent_result_id=NULL
-- Split parts have part_number=1,2,3... and parent_result_id pointing to original
CREATE TABLE result (
  result_id INTEGER PRIMARY KEY AUTOINCREMENT,  -- Sequential: 1, 2, 3...
  filepath TEXT NOT NULL UNIQUE,                -- Original file path (split parts: original_1, original_2)
  content TEXT NOT NULL,                        -- Full markdown content (or part content for splits)
  content_sha256 TEXT NOT NULL,                 -- SHA-256 hash for change detection
  part_number INTEGER DEFAULT NULL,             -- NULL=original/unsplit, 1,2,3...=split parts
  parent_result_id INTEGER DEFAULT NULL,        -- NULL=original, else points to parent result_id
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (parent_result_id) REFERENCES result(result_id)
);

-- Category definitions (loaded from prompts/*.yaml)
-- YAML key mapping: name -> category_name, description -> category_description
CREATE TABLE category (
  category_id INTEGER PRIMARY KEY AUTOINCREMENT,  -- Sequential: 1, 2, 3...
  category_filename TEXT NOT NULL,                -- e.g., "01_imperative_verbs.yaml"
  category_name TEXT NOT NULL,                    -- e.g., "imperative_verbs"
  category_description TEXT NOT NULL,             -- Human-readable description
  prompt_sha256 TEXT NOT NULL,                    -- SHA-256 hash of prompt for change detection
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(category_filename, prompt_sha256)        -- Same file + same hash = same category
);

-- Category assessment results per document
CREATE TABLE result_category (
  result_id INTEGER NOT NULL,
  category_id INTEGER NOT NULL,
  match TEXT NOT NULL CHECK(match IN ('yes', 'maybe', 'no', '1', '0')),
  reasoning_trace TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (result_id, category_id),
  FOREIGN KEY (result_id) REFERENCES result(result_id),
  FOREIGN KEY (category_id) REFERENCES category(category_id)
);

-- Extracted blockquotes as evidence (one row per quote)
CREATE TABLE result_category_blockquote (
  blockquote_id INTEGER PRIMARY KEY AUTOINCREMENT,
  result_id INTEGER NOT NULL,
  category_id INTEGER NOT NULL,
  blockquote TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (result_id) REFERENCES result(result_id),
  FOREIGN KEY (category_id) REFERENCES category(category_id)
);

-- Excluded files (binary, corrupt, etc) - tracked to avoid re-scanning
CREATE TABLE excluded_file (
  filepath TEXT PRIMARY KEY,             -- Original file path
  reason TEXT NOT NULL,                  -- Why it was excluded (e.g., "binary content (PNG image)")
  content_sha256 TEXT,                   -- Hash at time of exclusion (to detect if file changes)
  excluded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Processing run statistics (for tracking cumulative time across runs)
CREATE TABLE run_stats (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP,
  model TEXT NOT NULL,
  pairs_processed INTEGER DEFAULT 0,
  pairs_saved INTEGER DEFAULT 0,
  pairs_failed INTEGER DEFAULT 0,
  pairs_skipped INTEGER DEFAULT 0,
  processing_seconds REAL,           -- Time spent in vLLM requests
  janitor_imported INTEGER DEFAULT 0,
  janitor_seconds REAL,              -- Time spent in janitor import
  hostname TEXT,
  notes TEXT
);

-- View for cumulative processing stats
CREATE VIEW processing_summary AS
SELECT
  COUNT(*) as total_runs,
  SUM(pairs_processed) as total_pairs_processed,
  SUM(pairs_saved) as total_pairs_saved,
  SUM(pairs_failed) as total_pairs_failed,
  SUM(processing_seconds) as total_processing_seconds,
  SUM(janitor_imported) as total_janitor_imported,
  SUM(janitor_seconds) as total_janitor_seconds,
  ROUND(SUM(processing_seconds) / 3600.0, 2) as total_processing_hours,
  MIN(started_at) as first_run,
  MAX(finished_at) as last_run
FROM run_stats
WHERE finished_at IS NOT NULL;

-- Indexes for query performance
CREATE INDEX idx_result_category_match ON result_category(match);
CREATE INDEX idx_result_category_category ON result_category(category_id);
CREATE INDEX idx_blockquote_result_category ON result_category_blockquote(result_id, category_id);
CREATE INDEX idx_result_filepath ON result(filepath);
CREATE INDEX idx_result_content_sha256 ON result(content_sha256);
CREATE INDEX idx_result_parent ON result(parent_result_id);
CREATE INDEX idx_result_part ON result(part_number);
CREATE INDEX idx_category_filename ON category(category_filename);
CREATE INDEX idx_category_prompt_sha256 ON category(prompt_sha256);

-- Denormalized view for easy querying and datasette display
CREATE VIEW result_summary AS
SELECT
  r.result_id,
  r.filepath,
  r.content_sha256,
  r.created_at,
  COUNT(DISTINCT rc.category_id) as categories_processed,
  SUM(CASE WHEN rc.match IN ('yes', '1') THEN 1 ELSE 0 END) as yes_count,
  SUM(CASE WHEN rc.match = 'maybe' THEN 1 ELSE 0 END) as maybe_count,
  SUM(CASE WHEN rc.match IN ('no', '0') THEN 1 ELSE 0 END) as no_count,
  (SELECT COUNT(*) FROM result_category_blockquote rcb WHERE rcb.result_id = r.result_id) as total_blockquotes
FROM result r
LEFT JOIN result_category rc ON r.result_id = rc.result_id
GROUP BY r.result_id, r.filepath, r.content_sha256, r.created_at;

-- View for showing blockquotes with category names
CREATE VIEW blockquotes_by_category AS
SELECT
  rcb.result_id,
  r.filepath,
  c.category_id,
  c.category_name,
  c.category_description,
  rc.match,
  rcb.blockquote,
  rcb.created_at
FROM result_category_blockquote rcb
JOIN result r ON rcb.result_id = r.result_id
JOIN category c ON rcb.category_id = c.category_id
JOIN result_category rc ON rcb.result_id = rc.result_id AND rcb.category_id = rc.category_id
ORDER BY rcb.result_id, c.category_id;

-- View for category-by-category results (preserves original columns for compatibility)
CREATE VIEW category_matches AS
SELECT
  r.result_id,
  r.filepath,
  c.category_name,
  rc.match,
  rc.reasoning_trace,
  rc.created_at
FROM result_category rc
JOIN result r ON rc.result_id = r.result_id
JOIN category c ON rc.category_id = c.category_id
ORDER BY r.result_id, c.category_id;

-- View for aggregated results across split document parts
-- Shows original document with combined results from all parts
-- Match priority: yes > maybe > no (if any part says yes, document is yes)
CREATE VIEW document_category_aggregate AS
SELECT
  COALESCE(r.parent_result_id, r.result_id) as document_id,
  parent.filepath as original_filepath,
  c.category_id,
  c.category_name,
  c.category_description,
  -- Aggregate match: yes if any part yes, maybe if any part maybe, else no
  CASE
    WHEN SUM(CASE WHEN rc.match IN ('yes', '1') THEN 1 ELSE 0 END) > 0 THEN 'yes'
    WHEN SUM(CASE WHEN rc.match = 'maybe' THEN 1 ELSE 0 END) > 0 THEN 'maybe'
    ELSE 'no'
  END as aggregate_match,
  COUNT(DISTINCT r.result_id) as parts_processed,
  SUM(CASE WHEN rc.match IN ('yes', '1') THEN 1 ELSE 0 END) as yes_parts,
  SUM(CASE WHEN rc.match = 'maybe' THEN 1 ELSE 0 END) as maybe_parts,
  GROUP_CONCAT(DISTINCT r.part_number) as matching_parts
FROM result r
JOIN result_category rc ON r.result_id = rc.result_id
JOIN category c ON rc.category_id = c.category_id
LEFT JOIN result parent ON r.parent_result_id = parent.result_id
WHERE r.part_number IS NOT NULL  -- Only include split parts
GROUP BY COALESCE(r.parent_result_id, r.result_id), c.category_id;

-- View for blockquotes aggregated by original document (deduped)
CREATE VIEW document_blockquotes AS
SELECT DISTINCT
  COALESCE(r.parent_result_id, r.result_id) as document_id,
  COALESCE(parent.filepath, r.filepath) as original_filepath,
  c.category_id,
  c.category_name,
  rcb.blockquote
FROM result_category_blockquote rcb
JOIN result r ON rcb.result_id = r.result_id
JOIN category c ON rcb.category_id = c.category_id
LEFT JOIN result parent ON r.parent_result_id = parent.result_id
ORDER BY document_id, c.category_id;
