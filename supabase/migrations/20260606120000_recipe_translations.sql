-- Per-locale recipe content. `translations` holds {"en": {"name","instructions"},
-- "sv": {...}}; base name/instructions remain the canonical fallback. Reads pick
-- the active UI locale; missing locales are filled lazily/by backfill.
ALTER TABLE hearth.recipes
    ADD COLUMN IF NOT EXISTS translations jsonb NOT NULL DEFAULT '{}'::jsonb;
