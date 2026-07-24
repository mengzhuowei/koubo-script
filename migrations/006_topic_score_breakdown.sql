-- 选题评分升级：保存分项、评分方式、版本、置信度与阶段。
ALTER TABLE topics ADD COLUMN score_breakdown TEXT NULL AFTER score;
ALTER TABLE topics ADD COLUMN score_method VARCHAR(32) NULL AFTER score_breakdown;
ALTER TABLE topics ADD COLUMN score_version VARCHAR(32) NULL AFTER score_method;
ALTER TABLE topics ADD COLUMN score_confidence VARCHAR(16) NULL AFTER score_version;
ALTER TABLE topics ADD COLUMN score_stage VARCHAR(16) NULL AFTER score_confidence;
ALTER TABLE topics ADD COLUMN scored_at DATETIME NULL AFTER score_stage;

UPDATE topics
SET score_method = 'legacy',
    score_version = 'legacy-v1',
    score_confidence = 'unknown',
    score_stage = 'provisional',
    scored_at = updated_at
WHERE score_method IS NULL;
