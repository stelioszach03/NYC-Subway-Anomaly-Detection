-- Migration: add raw/predicted headway fields for online ML
-- Postgres only (TimescaleDB/PG16)

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'scores' AND column_name = 'headway_sec'
  ) THEN
    ALTER TABLE scores ADD COLUMN headway_sec double precision NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'scores' AND column_name = 'predicted_headway_sec'
  ) THEN
    ALTER TABLE scores ADD COLUMN predicted_headway_sec double precision NULL;
  END IF;
END
$$;
