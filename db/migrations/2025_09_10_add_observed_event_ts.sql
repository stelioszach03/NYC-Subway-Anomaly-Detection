-- Migration: add observed_ts and rename ts->event_ts if present
-- Postgres only (TimescaleDB/PG16)

DO $$
BEGIN
  -- Add observed_ts if not exists
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_name='scores' AND column_name='observed_ts'
  ) THEN
    ALTER TABLE scores ADD COLUMN observed_ts timestamptz NOT NULL DEFAULT now();
  END IF;

  -- If legacy 'ts' column exists and 'event_ts' is missing, rename
  IF EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_name='scores' AND column_name='ts'
  ) AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_name='scores' AND column_name='event_ts'
  ) THEN
    ALTER TABLE scores RENAME COLUMN ts TO event_ts;
  END IF;

  -- Create indexes on observed_ts
  IF NOT EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relname = 'ix_scores_observed_ts'
  ) THEN
    CREATE INDEX ix_scores_observed_ts ON scores (observed_ts DESC);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relname = 'ix_scores_observed_ts_route_stop'
  ) THEN
    CREATE INDEX ix_scores_observed_ts_route_stop ON scores (observed_ts DESC, route_id, stop_id);
  END IF;
END
$$;

