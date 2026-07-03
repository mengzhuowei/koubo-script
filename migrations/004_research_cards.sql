-- V0.2.1: 选题研究增强 - 本地资料卡
-- 资料卡是选题与脚本之间的中间产物，整理本地文章库相关资料供脚本生成引用
-- card_json 用 TEXT 存 json.dumps 字符串，与现有表（audience/hashtags）保持一致
CREATE TABLE IF NOT EXISTS topic_research_cards (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  topic_id INT NOT NULL,
  title VARCHAR(255) NOT NULL,
  summary MEDIUMTEXT,
  card_json MEDIUMTEXT NOT NULL,
  confidence VARCHAR(16) NOT NULL DEFAULT 'medium',
  local_source_count INT NOT NULL DEFAULT 0,
  web_source_count INT NOT NULL DEFAULT 0,
  has_official_source TINYINT NOT NULL DEFAULT 0,
  generated_by VARCHAR(64) NOT NULL DEFAULT 'llm',
  version INT NOT NULL DEFAULT 1,
  needs_refresh TINYINT NOT NULL DEFAULT 0,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_research_cards_topic FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_research_cards_topic_id ON topic_research_cards(topic_id);

-- 资料卡来源表：本地文章 / 联网搜索 / 手动添加
CREATE TABLE IF NOT EXISTS topic_research_sources (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  research_card_id INT NOT NULL,
  article_id INT,
  source_url VARCHAR(1024) NOT NULL,
  source_title VARCHAR(512),
  source_name VARCHAR(255),
  source_level VARCHAR(8),
  published_at DATETIME,
  source_type VARCHAR(32) NOT NULL DEFAULT 'local',
  excerpt MEDIUMTEXT,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_research_sources_card FOREIGN KEY (research_card_id) REFERENCES topic_research_cards(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_research_sources_card_id ON topic_research_sources(research_card_id);

-- scripts 表增加 research_card_id 字段，记录脚本使用了哪一份资料卡
ALTER TABLE scripts ADD COLUMN research_card_id INT NULL;
