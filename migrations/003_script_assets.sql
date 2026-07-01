-- V0.2: 发布素材包
-- 每个脚本一条素材记录（重新生成覆盖），存标题/封面/简介/标签/评论引导/置顶评论
-- JSON 字段统一用 TEXT 存 json.dumps 字符串，读取时手动 json.loads，与现有表（audience/hashtags）保持一致
CREATE TABLE IF NOT EXISTS script_assets (
  id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  script_id INT NOT NULL,
  titles TEXT,
  cover_texts TEXT,
  description MEDIUMTEXT,
  hashtags TEXT,
  comment_questions TEXT,
  pinned_comment VARCHAR(1024),
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_assets_script FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE CASCADE,
  UNIQUE KEY uk_assets_script (script_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
