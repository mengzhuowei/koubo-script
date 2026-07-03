-- V0.3: 联网搜索预算追踪
-- 每次联网搜索消耗记录一行，月度/单选题预算通过 SUM 聚合查询
CREATE TABLE IF NOT EXISTS web_search_usage (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  topic_id INT NOT NULL,
  query_text VARCHAR(512) NOT NULL,
  credits_used INT NOT NULL DEFAULT 0,
  results_count INT NOT NULL DEFAULT 0,
  search_depth VARCHAR(16) NOT NULL DEFAULT 'basic',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_web_usage_topic FOREIGN KEY (topic_id) REFERENCES topics(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 月度/选题预算查询通过 WHERE created_at >= '月初' AND created_at < '下月初' 走索引
CREATE INDEX idx_web_usage_topic_id ON web_search_usage(topic_id);
CREATE INDEX idx_web_usage_created_at ON web_search_usage(created_at);
