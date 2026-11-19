-- ============================================================================
-- 000 — rename every demo table to the Exchange style (2026-09-30)
-- ============================================================================
-- The IA Exchange Resources Style Guide names a table ex_<project abbr>_<name>,
-- its primary key id, and a foreign key <referenced table>_id. This project's
-- abbreviation is icc, and the FK names drop the ex_icc_ prefix
-- (alarm_flood_event_id, not ex_icc_alarm_flood_event_id). Record-keeping
-- timestamps end in _at (detected_at, created_at); event_time / start_time are
-- the time the thing happened and keep their names.
--
-- WHY THIS FILE SORTS FIRST. postgres-init replays sql/*.sql in order on every
-- `docker compose up`, against brand-new volumes and against the existing ones
-- on the demo laptop and the AI server alike. The create migrations that follow
-- (001..) now use the new names with CREATE ... IF NOT EXISTS, so on an
-- existing volume they would quietly create a second, empty set of tables
-- beside the old ones -- unless the old ones have already been renamed. On a
-- brand-new volume nothing here matches and the whole file is a no-op.
--
-- Idempotent: every step renames only when the old name exists and the new one
-- does not. One case needs more than that: if the gateway's Jython DDL
-- fallback got in first and created an EMPTY new table beside the old one, the
-- empty one is dropped and the old one renamed over it, so no data is stranded.
-- If both hold rows, nothing is touched and a WARNING says so.
--
-- Also: dashboard_widget_catalog is dropped (nothing has written it since
-- AlarmFloodWidgets was deleted), and stored tag paths are moved to the new
-- [default]Exchange/... tag roots so older flood events still resolve.
-- ============================================================================

CREATE FUNCTION pg_temp.rename_table(old_name text, new_name text) RETURNS void AS $$
DECLARE
	has_rows boolean;
BEGIN
	IF to_regclass('public.' || old_name) IS NULL THEN
		RETURN;
	END IF;
	IF to_regclass('public.' || new_name) IS NOT NULL THEN
		EXECUTE format('SELECT EXISTS (SELECT 1 FROM public.%I)', new_name) INTO has_rows;
		IF has_rows THEN
			RAISE WARNING 'Both % and % exist and % has rows -- left both alone, merge by hand',
				old_name, new_name, new_name;
			RETURN;
		END IF;
		EXECUTE format('DROP TABLE public.%I CASCADE', new_name);
		RAISE NOTICE 'Dropped empty % so % could be renamed over it', new_name, old_name;
	END IF;
	EXECUTE format('ALTER TABLE public.%I RENAME TO %I', old_name, new_name);
	RAISE NOTICE 'Renamed table % -> %', old_name, new_name;
END
$$ LANGUAGE plpgsql;

CREATE FUNCTION pg_temp.rename_column(tbl text, old_name text, new_name text) RETURNS void AS $$
BEGIN
	IF EXISTS (SELECT 1 FROM information_schema.columns
			   WHERE table_schema = 'public' AND table_name = tbl AND column_name = old_name)
	   AND NOT EXISTS (SELECT 1 FROM information_schema.columns
			   WHERE table_schema = 'public' AND table_name = tbl AND column_name = new_name) THEN
		EXECUTE format('ALTER TABLE public.%I RENAME COLUMN %I TO %I', tbl, old_name, new_name);
		RAISE NOTICE 'Renamed column %.% -> %', tbl, old_name, new_name;
	END IF;
END
$$ LANGUAGE plpgsql;

-- Indexes and sequences share one namespace with tables (pg_class).
CREATE FUNCTION pg_temp.rename_relation(kind text, old_name text, new_name text) RETURNS void AS $$
BEGIN
	IF to_regclass('public.' || old_name) IS NOT NULL
	   AND to_regclass('public.' || new_name) IS NULL THEN
		EXECUTE format('ALTER %s public.%I RENAME TO %I', kind, old_name, new_name);
	END IF;
END
$$ LANGUAGE plpgsql;

-- Foreign keys are constraints without a relation of their own.
CREATE FUNCTION pg_temp.rename_constraint(tbl text, old_name text, new_name text) RETURNS void AS $$
BEGIN
	IF to_regclass('public.' || tbl) IS NOT NULL
	   AND EXISTS (SELECT 1 FROM pg_constraint
				   WHERE conrelid = to_regclass('public.' || tbl) AND conname = old_name)
	   AND NOT EXISTS (SELECT 1 FROM pg_constraint
				   WHERE conrelid = to_regclass('public.' || tbl) AND conname = new_name) THEN
		EXECUTE format('ALTER TABLE public.%I RENAME CONSTRAINT %I TO %I', tbl, old_name, new_name);
	END IF;
END
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------- tables
DO $$
BEGIN
	PERFORM pg_temp.rename_table('alarm_flood_event',         'ex_icc_alarm_flood_event');
	PERFORM pg_temp.rename_table('alarm_flood_alarm',         'ex_icc_alarm_flood_alarm');
	PERFORM pg_temp.rename_table('alarm_flood_tag',           'ex_icc_alarm_flood_tag');
	PERFORM pg_temp.rename_table('agent_activity',            'ex_icc_agent_activity');
	PERFORM pg_temp.rename_table('dashboard_config',          'ex_icc_dashboard_config');
	PERFORM pg_temp.rename_table('dbwrecker_load',            'ex_icc_dbwrecker_load');
	PERFORM pg_temp.rename_table('demo_equipment_events',     'ex_icc_demo_equipment_events');
	PERFORM pg_temp.rename_table('equipment_downtime_events', 'ex_icc_equipment_downtime_events');
	PERFORM pg_temp.rename_table('security_audit_report',     'ex_icc_security_audit_report');
	PERFORM pg_temp.rename_table('tag_import_upload',         'ex_icc_tag_import_upload');
	PERFORM pg_temp.rename_table('tag_import_proposal',       'ex_icc_tag_import_proposal');
	PERFORM pg_temp.rename_table('tag_import_result',         'ex_icc_tag_import_result');
END
$$;

-- ---------------------------------------------------------------- columns
DO $$
BEGIN
	PERFORM pg_temp.rename_column('ex_icc_alarm_flood_event', 'event_id',        'id');
	PERFORM pg_temp.rename_column('ex_icc_alarm_flood_event', 'detected_ts',     'detected_at');
	PERFORM pg_temp.rename_column('ex_icc_alarm_flood_event', 'window_start_ts', 'window_start_at');
	PERFORM pg_temp.rename_column('ex_icc_alarm_flood_event', 'window_end_ts',   'window_end_at');
	PERFORM pg_temp.rename_column('ex_icc_alarm_flood_event', 'created_ts',      'created_at');
	PERFORM pg_temp.rename_column('ex_icc_alarm_flood_event', 'updated_ts',      'updated_at');
	PERFORM pg_temp.rename_column('ex_icc_alarm_flood_alarm', 'event_id',        'alarm_flood_event_id');
	PERFORM pg_temp.rename_column('ex_icc_alarm_flood_tag',   'event_id',        'alarm_flood_event_id');
	PERFORM pg_temp.rename_column('ex_icc_agent_activity',    'started_ts',      'started_at');
	PERFORM pg_temp.rename_column('ex_icc_agent_activity',    'finished_ts',     'finished_at');
	PERFORM pg_temp.rename_column('ex_icc_equipment_downtime_events', 'created_ts', 'created_at');
	PERFORM pg_temp.rename_column('ex_icc_security_audit_report', 'report_id',   'id');
	PERFORM pg_temp.rename_column('ex_icc_tag_import_upload',   'upload_id',     'id');
	PERFORM pg_temp.rename_column('ex_icc_tag_import_proposal', 'proposal_id',   'id');
	PERFORM pg_temp.rename_column('ex_icc_tag_import_proposal', 'upload_id',     'tag_import_upload_id');
	PERFORM pg_temp.rename_column('ex_icc_tag_import_result',   'result_id',     'id');
	PERFORM pg_temp.rename_column('ex_icc_tag_import_result',   'proposal_id',   'tag_import_proposal_id');
END
$$;

-- ---------------------------------------------------------------- sequences
-- Column defaults hold the sequence by OID, so a rename does not break them.
DO $$
BEGIN
	PERFORM pg_temp.rename_relation('SEQUENCE', 'alarm_flood_event_event_id_seq',      'ex_icc_alarm_flood_event_id_seq');
	PERFORM pg_temp.rename_relation('SEQUENCE', 'alarm_flood_alarm_id_seq',            'ex_icc_alarm_flood_alarm_id_seq');
	PERFORM pg_temp.rename_relation('SEQUENCE', 'alarm_flood_tag_id_seq',              'ex_icc_alarm_flood_tag_id_seq');
	PERFORM pg_temp.rename_relation('SEQUENCE', 'agent_activity_id_seq',               'ex_icc_agent_activity_id_seq');
	PERFORM pg_temp.rename_relation('SEQUENCE', 'dashboard_config_id_seq',             'ex_icc_dashboard_config_id_seq');
	PERFORM pg_temp.rename_relation('SEQUENCE', 'dbwrecker_load_id_seq',               'ex_icc_dbwrecker_load_id_seq');
	PERFORM pg_temp.rename_relation('SEQUENCE', 'demo_equipment_events_id_seq',        'ex_icc_demo_equipment_events_id_seq');
	PERFORM pg_temp.rename_relation('SEQUENCE', 'equipment_downtime_events_id_seq',    'ex_icc_equipment_downtime_events_id_seq');
	PERFORM pg_temp.rename_relation('SEQUENCE', 'security_audit_report_report_id_seq', 'ex_icc_security_audit_report_id_seq');
	PERFORM pg_temp.rename_relation('SEQUENCE', 'tag_import_upload_upload_id_seq',     'ex_icc_tag_import_upload_id_seq');
	PERFORM pg_temp.rename_relation('SEQUENCE', 'tag_import_proposal_proposal_id_seq', 'ex_icc_tag_import_proposal_id_seq');
	PERFORM pg_temp.rename_relation('SEQUENCE', 'tag_import_result_result_id_seq',     'ex_icc_tag_import_result_id_seq');
END
$$;

-- ---------------------------------------------------------------- indexes
-- Renaming a primary key's index renames the constraint with it.
DO $$
BEGIN
	PERFORM pg_temp.rename_relation('INDEX', 'alarm_flood_event_pkey',       'ex_icc_alarm_flood_event_pkey');
	PERFORM pg_temp.rename_relation('INDEX', 'alarm_flood_alarm_pkey',       'ex_icc_alarm_flood_alarm_pkey');
	PERFORM pg_temp.rename_relation('INDEX', 'alarm_flood_alarm_event_idx',  'ex_icc_alarm_flood_alarm_event_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'alarm_flood_tag_pkey',         'ex_icc_alarm_flood_tag_pkey');
	PERFORM pg_temp.rename_relation('INDEX', 'alarm_flood_tag_event_idx',    'ex_icc_alarm_flood_tag_event_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'agent_activity_pkey',          'ex_icc_agent_activity_pkey');
	PERFORM pg_temp.rename_relation('INDEX', 'agent_activity_agent_idx',     'ex_icc_agent_activity_agent_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'agent_activity_issue_idx',     'ex_icc_agent_activity_issue_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'agent_activity_started_idx',   'ex_icc_agent_activity_started_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'dashboard_config_pkey',        'ex_icc_dashboard_config_pkey');
	PERFORM pg_temp.rename_relation('INDEX', 'dashboard_config_name_key',    'ex_icc_dashboard_config_name_key');
	PERFORM pg_temp.rename_relation('INDEX', 'dashboard_config_purge_idx',   'ex_icc_dashboard_config_purge_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'dbwrecker_load_pkey',          'ex_icc_dbwrecker_load_pkey');
	PERFORM pg_temp.rename_relation('INDEX', 'idx_dbwrecker_load_tagid',     'ex_icc_dbwrecker_load_tagid_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'demo_equipment_events_pkey',   'ex_icc_demo_equipment_events_pkey');
	PERFORM pg_temp.rename_relation('INDEX', 'idx_demo_equipment_events_time', 'ex_icc_demo_equipment_events_time_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'idx_demo_equipment_events_area', 'ex_icc_demo_equipment_events_area_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'equipment_downtime_events_pkey', 'ex_icc_equipment_downtime_events_pkey');
	PERFORM pg_temp.rename_relation('INDEX', 'idx_equipment_downtime_events_time',
	                                        'ex_icc_equipment_downtime_events_time_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'idx_equipment_downtime_events_equipment',
	                                        'ex_icc_equipment_downtime_events_equipment_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'idx_equipment_downtime_events_equipment_reason',
	                                        'ex_icc_equipment_downtime_events_equipment_reason_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'security_audit_report_pkey',   'ex_icc_security_audit_report_pkey');
	PERFORM pg_temp.rename_relation('INDEX', 'idx_security_audit_report_generated',
	                                        'ex_icc_security_audit_report_generated_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'tag_import_upload_pkey',       'ex_icc_tag_import_upload_pkey');
	PERFORM pg_temp.rename_relation('INDEX', 'idx_tag_import_upload_time',   'ex_icc_tag_import_upload_time_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'tag_import_proposal_pkey',     'ex_icc_tag_import_proposal_pkey');
	PERFORM pg_temp.rename_relation('INDEX', 'idx_tag_import_proposal_upload', 'ex_icc_tag_import_proposal_upload_idx');
	PERFORM pg_temp.rename_relation('INDEX', 'tag_import_result_pkey',       'ex_icc_tag_import_result_pkey');
	PERFORM pg_temp.rename_relation('INDEX', 'idx_tag_import_result_proposal', 'ex_icc_tag_import_result_proposal_idx');
END
$$;

-- ---------------------------------------------------------------- foreign keys
DO $$
BEGIN
	PERFORM pg_temp.rename_constraint('ex_icc_alarm_flood_alarm',   'alarm_flood_alarm_event_id_fkey',
	                                 'ex_icc_alarm_flood_alarm_event_fkey');
	PERFORM pg_temp.rename_constraint('ex_icc_alarm_flood_tag',     'alarm_flood_tag_event_id_fkey',
	                                 'ex_icc_alarm_flood_tag_event_fkey');
	PERFORM pg_temp.rename_constraint('ex_icc_tag_import_proposal', 'tag_import_proposal_upload_id_fkey',
	                                 'ex_icc_tag_import_proposal_upload_fkey');
	PERFORM pg_temp.rename_constraint('ex_icc_tag_import_result',   'tag_import_result_proposal_id_fkey',
	                                 'ex_icc_tag_import_result_proposal_fkey');
END
$$;

-- ---------------------------------------------------------------- demo_housekeeping
-- The one table whose key was not a surrogate: job was the primary key. The
-- guide wants an auto-increment id as the FIRST column, which ALTER TABLE
-- cannot place, so the table is rebuilt rather than renamed. It holds one row
-- per nightly job.
DO $$
BEGIN
	IF to_regclass('public.demo_housekeeping') IS NOT NULL THEN
		CREATE TABLE IF NOT EXISTS ex_icc_demo_housekeeping (
			id            SERIAL      NOT NULL,
			job           VARCHAR(64) NOT NULL,
			last_run_date DATE,
			last_run_at   TIMESTAMP,
			last_result   TEXT,
			CONSTRAINT ex_icc_demo_housekeeping_pkey PRIMARY KEY (id),
			CONSTRAINT ex_icc_demo_housekeeping_job_key UNIQUE (job)
		);
		INSERT INTO ex_icc_demo_housekeeping (job, last_run_date, last_run_at, last_result)
		SELECT o.job, o.last_run_date, o.last_run_ts, o.last_result
		FROM demo_housekeeping o
		WHERE NOT EXISTS (SELECT 1 FROM ex_icc_demo_housekeeping n WHERE n.job = o.job);
		DROP TABLE demo_housekeeping;
		RAISE NOTICE 'Rebuilt demo_housekeeping as ex_icc_demo_housekeeping';
	END IF;
END
$$;

-- ---------------------------------------------------------------- dropped
DROP TABLE IF EXISTS dashboard_widget_catalog;

-- ---------------------------------------------------------------- tag paths
-- Tags moved from [default]Alarm Flood/... to [default]Exchange/Alarm Flood/...
-- and from [default]Tag Import Agent/... to [default]Exchange/Tag Import Agent/...
-- (UDT types likewise under _types_/Exchange/). Stored events carry the old
-- paths in plain columns and inside their JSON, and the trend endpoint only
-- charts tags under the new root, so an old event would otherwise chart
-- nothing. The pattern only matches a root NOT already preceded by '/', which
-- is what makes a replay a no-op.
DO $$
BEGIN
	IF to_regclass('public.ex_icc_alarm_flood_tag') IS NOT NULL THEN
		UPDATE ex_icc_alarm_flood_tag
		SET tag_path    = regexp_replace(tag_path, '(^|[^/])Alarm Flood/', '\1Exchange/Alarm Flood/', 'g'),
			config_json = CAST(regexp_replace(CAST(config_json AS text),
							'(^|[^/])Alarm Flood/', '\1Exchange/Alarm Flood/', 'g') AS jsonb)
		WHERE tag_path ~ '(^|[^/])Alarm Flood/'
		   OR CAST(config_json AS text) ~ '(^|[^/])Alarm Flood/';
	END IF;
	IF to_regclass('public.ex_icc_alarm_flood_alarm') IS NOT NULL THEN
		UPDATE ex_icc_alarm_flood_alarm
		SET tag_path     = regexp_replace(tag_path, '(^|[^/])Alarm Flood/', '\1Exchange/Alarm Flood/', 'g'),
			source       = regexp_replace(source, '(^|[^/])Alarm Flood/', '\1Exchange/Alarm Flood/', 'g'),
			display_path = regexp_replace(display_path, '(^|[^/])Alarm Flood/', '\1Exchange/Alarm Flood/', 'g')
		WHERE tag_path ~ '(^|[^/])Alarm Flood/'
		   OR source ~ '(^|[^/])Alarm Flood/'
		   OR display_path ~ '(^|[^/])Alarm Flood/';
	END IF;
	IF to_regclass('public.ex_icc_alarm_flood_event') IS NOT NULL THEN
		UPDATE ex_icc_alarm_flood_event
		SET summary_json   = CAST(regexp_replace(CAST(summary_json AS text),
								'(^|[^/])Alarm Flood/', '\1Exchange/Alarm Flood/', 'g') AS jsonb),
			dashboard_json = CAST(regexp_replace(CAST(dashboard_json AS text),
								'(^|[^/])Alarm Flood/', '\1Exchange/Alarm Flood/', 'g') AS jsonb),
			analysis_json  = CAST(regexp_replace(CAST(analysis_json AS text),
								'(^|[^/])Alarm Flood/', '\1Exchange/Alarm Flood/', 'g') AS jsonb)
		WHERE CAST(summary_json AS text) ~ '(^|[^/])Alarm Flood/'
		   OR CAST(dashboard_json AS text) ~ '(^|[^/])Alarm Flood/'
		   OR CAST(analysis_json AS text) ~ '(^|[^/])Alarm Flood/';
	END IF;
	IF to_regclass('public.ex_icc_dashboard_config') IS NOT NULL THEN
		UPDATE ex_icc_dashboard_config
		SET widgets_json = CAST(regexp_replace(CAST(widgets_json AS text),
								'(^|[^/])Alarm Flood/', '\1Exchange/Alarm Flood/', 'g') AS jsonb)
		WHERE CAST(widgets_json AS text) ~ '(^|[^/])Alarm Flood/';
	END IF;
	IF to_regclass('public.ex_icc_tag_import_result') IS NOT NULL THEN
		UPDATE ex_icc_tag_import_result
		SET tag_path = regexp_replace(tag_path, '(\]|_types_/)Tag Import Agent', '\1Exchange/Tag Import Agent')
		WHERE tag_path ~ '(\]|_types_/)Tag Import Agent';
	END IF;
END
$$;
