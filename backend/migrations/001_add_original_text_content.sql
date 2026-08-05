-- Adds content_drafts.original_text_content: the caption as first uploaded,
-- preserved once a cleaned caption replaces text_content. Mirrors the photo
-- remediation flow, which writes the cleaned image to a NEW blob and never
-- overwrites the original.
--
-- Nullable, so this is safe to run against a live database — the currently
-- running application code never references this column (SQLAlchemy emits
-- explicit column lists, not SELECT *), so old and new code both keep
-- working regardless of which is deployed when this runs.
--
-- Idempotent: safe to run more than once, and safe to run on an environment
-- that already has it.
--
-- Run manually against each environment (no migration tooling in this repo —
-- see the "Deliberately rejected" note this decision reverses, in
-- git history / project notes, for why: db.create_all() never ALTERs an
-- existing table). Must be applied and verified on every environment BEFORE
-- code referencing this column is deployed there.

IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('dbo.content_drafts')
      AND name = 'original_text_content'
)
    ALTER TABLE dbo.content_drafts
    ADD original_text_content NVARCHAR(MAX) NULL;
