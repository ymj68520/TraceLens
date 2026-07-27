-- Migration 003: repair the broken super_admin seed (password + email).
--
-- Migration 001's seed for the default super_admin (username 'super_admin') ships
-- two values that the application's OWN schema rejects, making the distributed
-- server's documented auth path unusable out of the box:
--
--   1. password_hash does NOT verify against its documented password 'admin123'
--      (the literal hash in 001 is stale/incorrect) → POST /api/auth/login always
--      fails with 401, so no environment seeded by 001 can log in.
--   2. email 'super_admin@tracelens.local' uses the reserved special-use .local
--      TLD, which Pydantic EmailStr (UserBase.email) rejects → GET /api/auth/me
--      raises 500 on serialization for the seed user.
--
-- This migration corrects both, but ONLY for rows that still carry the known-bad
-- values (non-destructive): if an operator has already changed the password or
-- email, those are left untouched. Idempotent (no-op once the bad values are gone).
--
-- (CHANGE IN PRODUCTION — same caveat as 001.)

UPDATE users
SET password_hash = '$2b$12$rF2iZrZBlu7moUIKpNn1vOqYJe/LbNJ9.6C4pcbRx2iJUk4x9CR2.'
WHERE username = 'super_admin'
  AND password_hash = '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5GyY9wqDf11qO';

UPDATE users
SET email = 'super_admin@example.com'
WHERE username = 'super_admin'
  AND email = 'super_admin@tracelens.local';
