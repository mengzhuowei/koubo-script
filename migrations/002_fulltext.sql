-- V0.2: articles 全文搜索索引
-- 使用 ngram 解析器以支持中文分词（MySQL 8.0 内置，默认 token 大小 2）
-- 覆盖标题与正文，供文章池搜索使用 MATCH ... AGAINST
CREATE FULLTEXT INDEX idx_articles_fulltext ON articles(title, content_text) WITH PARSER ngram;
