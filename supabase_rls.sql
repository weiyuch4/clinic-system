-- ── Supabase Row Level Security — run once in the SQL editor ──────────────────
--
-- What this does:
--   1. Enables RLS on every data table (PHI-containing tables with clinic_id).
--   2. FORCE ROW SECURITY makes the policy apply to the 'postgres' role too
--      (table owners bypass RLS by default in PostgreSQL).
--   3. The policy allows a row only when its clinic_id matches the PostgreSQL
--      session variable 'app.clinic_id', which the app sets at the start of
--      every transaction via db._conn().
--   4. Auth tables (users, refresh_tokens, clinics, clinic_settings) are
--      intentionally excluded — they contain no PHI and are queried before
--      the clinic_id is known (login flow).
--
-- After running this, the app's existing clinic_id= filters in Python become
-- a double-checked safety net: even if a bug bypasses the Python filter, the
-- DB will block the cross-clinic row at the PostgreSQL level.
-- ──────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    tbl TEXT;
    data_tables TEXT[] := ARRAY[
        'contacts',
        'submitted',
        'excluded',
        'mspt_phone_completed',
        'mspt_blood_used',
        'mspt_completed',
        'mspt_checkedin',
        'mspt_manual',
        'on_hold',
        'manual_pickups',
        'hep_returned_completed',
        'line_notification_log',
        'line_unlinked',
        'line_recently_sent',
        'alleypin_not_found',
        'shifts',
        'nurses',
        'published_weeks',
        'bulletin_notes',
        'salary_records',
        'synced_candidates',
        'lab_reports',
        'clinic_contacts'
    ];
BEGIN
    FOREACH tbl IN ARRAY data_tables LOOP
        -- Skip if table doesn't exist yet (safe during incremental deploys)
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = tbl
        ) THEN
            RAISE NOTICE 'Table % does not exist, skipping.', tbl;
            CONTINUE;
        END IF;

        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);

        -- Drop existing policy if re-running this script
        EXECUTE format(
            'DROP POLICY IF EXISTS clinic_isolation ON %I', tbl
        );

        -- Allow rows only when clinic_id matches the session variable.
        -- current_setting(..., true) returns NULL (not an error) when the
        -- variable is not set — NULL = int is false, so no rows leak.
        EXECUTE format($$
            CREATE POLICY clinic_isolation ON %I
            USING (
                clinic_id = current_setting('app.clinic_id', true)::int
            )
            WITH CHECK (
                clinic_id = current_setting('app.clinic_id', true)::int
            )
        $$, tbl);

        RAISE NOTICE 'RLS enabled on %', tbl;
    END LOOP;
END;
$$;
