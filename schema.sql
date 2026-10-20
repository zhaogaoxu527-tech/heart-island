-- ============================================================
--  心屿 · AI 女友（登录版）SQLite 建表脚本
--  应用启动时自动执行；也可以手动执行：
--      sqlite3 data/heart_island.db < schema.sql
-- ============================================================

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
-- 用户表
-- 密码字段保存的是 Werkzeug 生成的不可逆哈希，不是明文。
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS "user" (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password  TEXT NOT NULL,
    email     TEXT NOT NULL UNIQUE COLLATE NOCASE
);

-- ------------------------------------------------------------
-- 聊天记录表
-- 同一 username + girl_name + girl_char 构成一套独立的人设对话空间。
-- role = 'user'      用户提问
-- role = 'assistant' AI 女友回复
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT    NOT NULL COLLATE NOCASE,
    girl_name   TEXT    NOT NULL,
    girl_char   TEXT    NOT NULL,
    role        TEXT    NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT    NOT NULL,
    create_time TEXT    NOT NULL,
    FOREIGN KEY (username) REFERENCES "user" (username) ON DELETE CASCADE
);

-- 按「用户 + 女友名 + 性格」加载全部历史记录
CREATE INDEX IF NOT EXISTS idx_chat_history_lookup
    ON chat_history (username, girl_name, girl_char, id);

-- 查询当前用户最近使用过的人设
CREATE INDEX IF NOT EXISTS idx_chat_history_user_recent
    ON chat_history (username, id DESC);
