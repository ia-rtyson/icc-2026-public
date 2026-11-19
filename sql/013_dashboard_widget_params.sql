-- ============================================================================
-- 013 — dashboard template params snake_case -> camelCase in saved layouts
-- ============================================================================
-- The Dashboard Agent's template views took their params in snake_case
-- (tag_path, line_path, minutes_back, ...). The style guide names a view param
-- propertyName, so the templates now take tagPath, linePath, minutesBack, ...
-- A saved layout in ex_icc_dashboard_config stores each widget's viewParams
-- verbatim, so a row saved before the rename would open with every chart empty:
-- the template would read view.params.tagPath and find nothing.
--
-- This rewrites only the eight keys that were renamed, and only inside
-- widgets[*].viewParams. Every other key -- header, footer, metric, points,
-- stations, content, _description, anything already camelCase -- is left
-- exactly as it is. A widget that somehow carries both spellings keeps the
-- camelCase value and loses the snake_case one.
--
-- Idempotent: once a row has no old key left, the WHERE clause skips it, so
-- replaying this on every `docker compose up` (postgres-init) changes nothing.
-- Rows that are not an array of widget objects (the pre-fix _toPlain bug saved
-- some as lists of key names) are skipped rather than touched.
-- ============================================================================

CREATE FUNCTION pg_temp.camel_widget_params(params jsonb) RETURNS jsonb AS $$
DECLARE
	renames CONSTANT text[][] := ARRAY[
		['tag_paths', 'tagPaths'],
		['tag_path', 'tagPath'],
		['line_path', 'linePath'],
		['minutes_back', 'minutesBack'],
		['hours_back', 'hoursBack'],
		['bucket_minutes', 'bucketMinutes'],
		['eng_high', 'engHigh'],
		['value_name', 'valueName']
	];
	out jsonb := params;
	i int;
BEGIN
	FOR i IN 1 .. array_length(renames, 1) LOOP
		IF out ? renames[i][1] THEN
			IF NOT out ? renames[i][2] THEN
				out := out || jsonb_build_object(renames[i][2], out -> renames[i][1]);
			END IF;
			out := out - renames[i][1];
		END IF;
	END LOOP;
	RETURN out;
END
$$ LANGUAGE plpgsql IMMUTABLE;

DO $$
BEGIN
	IF to_regclass('public.ex_icc_dashboard_config') IS NULL THEN
		RETURN;
	END IF;

	UPDATE ex_icc_dashboard_config c
	SET widgets_json = (
		SELECT jsonb_agg(
			CASE
				WHEN jsonb_typeof(t.w) = 'object' AND jsonb_typeof(t.w -> 'viewParams') = 'object'
					THEN jsonb_set(t.w, '{viewParams}', pg_temp.camel_widget_params(t.w -> 'viewParams'))
				ELSE t.w
			END
			ORDER BY t.ord)
		FROM jsonb_array_elements(c.widgets_json) WITH ORDINALITY AS t(w, ord))
	WHERE jsonb_typeof(c.widgets_json) = 'array'
		AND EXISTS (
			SELECT 1
			FROM jsonb_array_elements(c.widgets_json) AS e(w)
			WHERE jsonb_typeof(e.w) = 'object'
				AND jsonb_typeof(e.w -> 'viewParams') = 'object'
				AND (e.w -> 'viewParams') ?| ARRAY['tag_paths', 'tag_path', 'line_path', 'minutes_back',
					'hours_back', 'bucket_minutes', 'eng_high', 'value_name']);
END
$$;
