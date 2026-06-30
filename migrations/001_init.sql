-- AI Agent Efficiency Coach MVP 初始化 schema
-- 可重复执行：使用 IF NOT EXISTS，不破坏已有数据。

CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  type TEXT NOT NULL,
  level TEXT NOT NULL DEFAULT 'B',
  keywords TEXT,
  config_json TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  fetch_interval_minutes INTEGER NOT NULL DEFAULT 1440,
  last_cursor TEXT,
  last_seen_item_id TEXT,
  last_fetched_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER,
  source_item_id TEXT,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  canonical_url TEXT,
  author TEXT,
  published_at TEXT,
  raw_html TEXT,
  content_text TEXT,
  summary TEXT,
  key_points TEXT,
  content_hash TEXT NOT NULL,
  language TEXT,
  fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processed_at TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  FOREIGN KEY (source_id) REFERENCES sources(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_content_hash ON articles(content_hash);
CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_source_item ON articles(source_id, source_item_id)
  WHERE source_item_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_canonical_url ON articles(canonical_url)
  WHERE canonical_url IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_source_id ON articles(source_id);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);

CREATE TABLE IF NOT EXISTS topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  one_line_takeaway TEXT,
  summary TEXT,
  category TEXT,
  audience TEXT,
  recommended_column TEXT,
  recommended_platform TEXT,
  recommended_duration INTEGER,
  score INTEGER NOT NULL DEFAULT 0,
  source_level TEXT,
  actionable_value TEXT,
  risk_notes TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_topics_score ON topics(score);
CREATE INDEX IF NOT EXISTS idx_topics_status ON topics(status);

CREATE TABLE IF NOT EXISTS topic_articles (
  topic_id INTEGER NOT NULL,
  article_id INTEGER NOT NULL,
  PRIMARY KEY (topic_id, article_id),
  FOREIGN KEY (topic_id) REFERENCES topics(id),
  FOREIGN KEY (article_id) REFERENCES articles(id)
);

CREATE TABLE IF NOT EXISTS topic_facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_id INTEGER NOT NULL,
  claim TEXT NOT NULL,
  source_url TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'medium',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (topic_id) REFERENCES topics(id)
);

CREATE INDEX IF NOT EXISTS idx_topic_facts_topic_id ON topic_facts(topic_id);

CREATE TABLE IF NOT EXISTS scripts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_id INTEGER NOT NULL,
  platform TEXT NOT NULL,
  format TEXT NOT NULL,
  duration INTEGER NOT NULL,
  title TEXT,
  hook TEXT,
  body TEXT NOT NULL,
  cta TEXT,
  cover_text TEXT,
  description TEXT,
  hashtags TEXT,
  version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (topic_id) REFERENCES topics(id)
);

CREATE INDEX IF NOT EXISTS idx_scripts_topic_id ON scripts(topic_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_scripts_version ON scripts(topic_id, platform, format, duration, version);

CREATE TABLE IF NOT EXISTS creator_profile (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  positioning TEXT NOT NULL,
  target_audience TEXT,
  tone TEXT,
  content_boundary TEXT,
  default_cta TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS llm_settings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL DEFAULT 'openai',
  model TEXT NOT NULL,
  temperature REAL NOT NULL DEFAULT 0.4,
  max_tokens INTEGER NOT NULL DEFAULT 2000,
  api_key_env_var TEXT NOT NULL DEFAULT 'OPENAI_API_KEY',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,
  payload_json TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  locked_by TEXT,
  heartbeat_at TEXT,
  error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TEXT,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_type ON jobs(type);
CREATE INDEX IF NOT EXISTS idx_jobs_available_at ON jobs(available_at);
