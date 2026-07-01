-- 口播雷达 MVP 初始化 schema（MySQL 8.0+）
-- 注意：MySQL 不支持 CREATE INDEX IF NOT EXISTS，本文件只能由 schema_migrations 表
-- 保证只执行一次。首次部署时数据库必须为空库。

CREATE TABLE IF NOT EXISTS sources (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  url VARCHAR(1024) NOT NULL,
  type VARCHAR(32) NOT NULL,
  level VARCHAR(8) NOT NULL DEFAULT 'B',
  keywords VARCHAR(512),
  config_json TEXT,
  enabled TINYINT NOT NULL DEFAULT 1,
  fetch_interval_minutes INT NOT NULL DEFAULT 1440,
  last_cursor VARCHAR(255),
  last_seen_item_id VARCHAR(255),
  last_fetched_at DATETIME,
  last_error TEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS articles (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  source_id INT,
  source_item_id VARCHAR(512),
  title VARCHAR(1024) NOT NULL,
  url VARCHAR(1024) NOT NULL,
  canonical_url VARCHAR(1024),
  author VARCHAR(255),
  published_at DATETIME,
  raw_html LONGTEXT,
  content_text LONGTEXT,
  summary MEDIUMTEXT,
  key_points MEDIUMTEXT,
  content_hash VARCHAR(64) NOT NULL,
  language VARCHAR(16),
  fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  processed_at DATETIME,
  status VARCHAR(16) NOT NULL DEFAULT 'new',
  CONSTRAINT fk_articles_source FOREIGN KEY (source_id) REFERENCES sources(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE UNIQUE INDEX idx_articles_content_hash ON articles(content_hash);
-- MySQL 不支持部分索引 WHERE，但唯一索引中多个 NULL 视为不同值，等价于原 SQLite 行为
CREATE UNIQUE INDEX idx_articles_source_item ON articles(source_id, source_item_id);
-- utf8mb4 下 VARCHAR(1024) 索引达 4096 字节超过 3072 限制，使用前缀 768 字符（=3072 字节）
CREATE UNIQUE INDEX idx_articles_canonical_url ON articles(canonical_url(768));
CREATE INDEX idx_articles_published_at ON articles(published_at);
CREATE INDEX idx_articles_source_id ON articles(source_id);
CREATE INDEX idx_articles_status ON articles(status);

CREATE TABLE IF NOT EXISTS topics (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  title VARCHAR(512) NOT NULL,
  one_line_takeaway VARCHAR(1024),
  summary MEDIUMTEXT,
  category VARCHAR(64),
  audience TEXT,
  recommended_column VARCHAR(64),
  recommended_platform VARCHAR(32),
  recommended_duration INT,
  score INT NOT NULL DEFAULT 0,
  source_level VARCHAR(8),
  actionable_value TEXT,
  risk_notes TEXT,
  status VARCHAR(16) NOT NULL DEFAULT 'new',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_topics_score ON topics(score);
CREATE INDEX idx_topics_status ON topics(status);

CREATE TABLE IF NOT EXISTS topic_articles (
  topic_id INT NOT NULL,
  article_id INT NOT NULL,
  PRIMARY KEY (topic_id, article_id),
  CONSTRAINT fk_ta_topic FOREIGN KEY (topic_id) REFERENCES topics(id),
  CONSTRAINT fk_ta_article FOREIGN KEY (article_id) REFERENCES articles(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS topic_facts (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  topic_id INT NOT NULL,
  claim TEXT NOT NULL,
  source_url VARCHAR(1024) NOT NULL,
  confidence VARCHAR(16) NOT NULL DEFAULT 'medium',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_facts_topic FOREIGN KEY (topic_id) REFERENCES topics(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_topic_facts_topic_id ON topic_facts(topic_id);

CREATE TABLE IF NOT EXISTS scripts (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  topic_id INT NOT NULL,
  platform VARCHAR(32) NOT NULL,
  format VARCHAR(32) NOT NULL,
  duration INT NOT NULL,
  title VARCHAR(512),
  hook VARCHAR(1024),
  body LONGTEXT NOT NULL,
  cta VARCHAR(1024),
  cover_text VARCHAR(255),
  description MEDIUMTEXT,
  hashtags TEXT,
  version INT NOT NULL DEFAULT 1,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_scripts_topic FOREIGN KEY (topic_id) REFERENCES topics(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_scripts_topic_id ON scripts(topic_id);
CREATE UNIQUE INDEX idx_scripts_version ON scripts(topic_id, platform, format, duration, version);

CREATE TABLE IF NOT EXISTS creator_profile (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(64) NOT NULL,
  positioning VARCHAR(512) NOT NULL,
  target_audience VARCHAR(512),
  tone VARCHAR(255),
  content_boundary VARCHAR(512),
  default_cta VARCHAR(512),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS llm_settings (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  provider VARCHAR(32) NOT NULL DEFAULT 'openai',
  model VARCHAR(64) NOT NULL,
  temperature FLOAT NOT NULL DEFAULT 0.4,
  max_tokens INT NOT NULL DEFAULT 2000,
  api_key_env_var VARCHAR(64) NOT NULL DEFAULT 'OPENAI_API_KEY',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS jobs (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  type VARCHAR(32) NOT NULL,
  payload_json TEXT,
  status VARCHAR(16) NOT NULL DEFAULT 'pending',
  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 3,
  available_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  locked_by VARCHAR(64),
  heartbeat_at DATETIME,
  error TEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  started_at DATETIME,
  finished_at DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_type ON jobs(type);
CREATE INDEX idx_jobs_available_at ON jobs(available_at);
