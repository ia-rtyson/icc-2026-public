-- The default dashboard the Dashboard Agent page opens on.
--
-- The page used to open on an empty grid, because a layout is session state and
-- nothing put one there. Its root's onStartup now loads the dashboard named
-- exchange.dashboard.configs.DEFAULT_NAME ("Line Overview") from this table, so
-- this file is what guarantees that row exists -- on a fresh volume, on the AI
-- server, and after anyone deletes it by hand in psql. (The Saved popup refuses
-- to delete it or clear its demo flag, so the nightly purge cannot take it.)
--
-- Seeded only when no row of that name exists: replaying never overwrites a
-- layout someone has since re-saved as "Line Overview" from the page, which is
-- the intended way to change the default.
--
-- The layout (2026-10-15): torque and current sparklines plus a
-- Packaging-infeed ring (rows 1-3), Sankey and station-rate Bar (rows 4-8), and
-- the alarm Heatmap across the full width (rows 9-12). Six widgets, not the
-- original eight: the Throughput-loss Funnel and the Drive-precursors Area were
-- dropped because neither was readable at a third of the grid's width.

INSERT INTO ex_icc_dashboard_config (name, widgets_json, is_demo)
SELECT 'Line Overview', CAST($json$
[
	{
		"body": {
			"style": {
				"classes": ""
			}
		},
		"name": "torque-spark",
		"style": {
			"classes": ""
		},
		"header": {
			"style": {
				"classes": ""
			},
			"title": "",
			"enabled": false
		},
		"minSize": {
			"rowSpan": 2,
			"columnSpan": 2
		},
		"position": {
			"rowEnd": 4,
			"rowStart": 1,
			"columnEnd": 6,
			"columnStart": 1
		},
		"viewPath": "Exchange/Dashboard Agent/Dashboard Templates/sparkline",
		"viewParams": {
			"footer": "% - last 15 min",
			"header": "Drive torque",
			"points": 60,
			"tagPath": "[default]Exchange/Alarm Flood/Site1/Area1/Line1/Packaging/MotorTorque",
			"minutesBack": 15
		},
		"isConfigurable": false
	},
	{
		"body": {
			"style": {
				"classes": ""
			}
		},
		"name": "current-spark",
		"style": {
			"classes": ""
		},
		"header": {
			"style": {
				"classes": ""
			},
			"title": "",
			"enabled": false
		},
		"minSize": {
			"rowSpan": 2,
			"columnSpan": 2
		},
		"position": {
			"rowEnd": 4,
			"rowStart": 1,
			"columnEnd": 11,
			"columnStart": 6
		},
		"viewPath": "Exchange/Dashboard Agent/Dashboard Templates/sparkline",
		"viewParams": {
			"footer": "A - last 15 min",
			"header": "Drive current",
			"points": 60,
			"tagPath": "[default]Exchange/Alarm Flood/Site1/Area1/Line1/Packaging/MotorCurrent",
			"minutesBack": 15
		},
		"isConfigurable": false
	},
	{
		"body": {
			"style": {
				"classes": ""
			}
		},
		"name": "infeed-ring",
		"style": {
			"classes": ""
		},
		"header": {
			"style": {
				"classes": ""
			},
			"title": "",
			"enabled": false
		},
		"minSize": {
			"rowSpan": 2,
			"columnSpan": 2
		},
		"position": {
			"rowEnd": 4,
			"rowStart": 1,
			"columnEnd": 15,
			"columnStart": 11
		},
		"viewPath": "Exchange/Dashboard Agent/Dashboard Templates/ring",
		"viewParams": {
			"footer": "% full",
			"header": "Packaging infeed",
			"engHigh": 100,
			"tagPath": "[default]Exchange/Alarm Flood/Site1/Area1/Line1/Packaging/InfeedBufferLevel"
		},
		"isConfigurable": false
	},
	{
		"body": {
			"style": {
				"classes": ""
			}
		},
		"name": "flow-sankey",
		"style": {
			"classes": ""
		},
		"header": {
			"style": {
				"classes": ""
			},
			"title": "",
			"enabled": false
		},
		"minSize": {
			"rowSpan": 2,
			"columnSpan": 2
		},
		"position": {
			"rowEnd": 9,
			"rowStart": 4,
			"columnEnd": 9,
			"columnStart": 1
		},
		"viewPath": "Exchange/Dashboard Agent/Dashboard Templates/sankey",
		"viewParams": {
			"footer": "% of each station's nominal rate",
			"header": "Material flow",
			"linePath": ""
		},
		"isConfigurable": false
	},
	{
		"body": {
			"style": {
				"classes": ""
			}
		},
		"name": "rate-bars",
		"style": {
			"classes": ""
		},
		"header": {
			"style": {
				"classes": ""
			},
			"title": "",
			"enabled": false
		},
		"minSize": {
			"rowSpan": 2,
			"columnSpan": 2
		},
		"position": {
			"rowEnd": 9,
			"rowStart": 4,
			"columnEnd": 15,
			"columnStart": 9
		},
		"viewPath": "Exchange/Dashboard Agent/Dashboard Templates/station-bar",
		"viewParams": {
			"footer": "% of nominal throughput",
			"header": "Station rate",
			"metric": "rate",
			"linePath": ""
		},
		"isConfigurable": false
	},
	{
		"body": {
			"style": {
				"classes": ""
			}
		},
		"name": "alarm-heatmap",
		"style": {
			"classes": ""
		},
		"header": {
			"style": {
				"classes": ""
			},
			"title": "",
			"enabled": false
		},
		"minSize": {
			"rowSpan": 2,
			"columnSpan": 3
		},
		"position": {
			"rowEnd": 13,
			"rowStart": 9,
			"columnEnd": 15,
			"columnStart": 1
		},
		"viewPath": "Exchange/Dashboard Agent/Dashboard Templates/heatmap",
		"viewParams": {
			"footer": "Last 12 h, 30 min buckets",
			"header": "Alarm density",
			"linePath": "",
			"hoursBack": 12,
			"bucketMinutes": 30
		},
		"isConfigurable": false
	}
]
$json$ AS jsonb), TRUE
WHERE NOT EXISTS (
	SELECT 1 FROM ex_icc_dashboard_config WHERE lower(name) = 'line overview'
);

-- A gateway that already holds the ORIGINAL eight-widget Line Overview (seeded
-- by hand 2026-10-01, before this file existed) gets the six-widget layout
-- above. Matched on the two dropped widgets still being present, so a layout
-- someone has since re-saved without them is left alone, and a replay is a
-- no-op.
UPDATE ex_icc_dashboard_config
SET widgets_json = (
	SELECT widgets_json FROM (VALUES (CAST($json$
[
	{
		"body": {
			"style": {
				"classes": ""
			}
		},
		"name": "torque-spark",
		"style": {
			"classes": ""
		},
		"header": {
			"style": {
				"classes": ""
			},
			"title": "",
			"enabled": false
		},
		"minSize": {
			"rowSpan": 2,
			"columnSpan": 2
		},
		"position": {
			"rowEnd": 4,
			"rowStart": 1,
			"columnEnd": 6,
			"columnStart": 1
		},
		"viewPath": "Exchange/Dashboard Agent/Dashboard Templates/sparkline",
		"viewParams": {
			"footer": "% - last 15 min",
			"header": "Drive torque",
			"points": 60,
			"tagPath": "[default]Exchange/Alarm Flood/Site1/Area1/Line1/Packaging/MotorTorque",
			"minutesBack": 15
		},
		"isConfigurable": false
	},
	{
		"body": {
			"style": {
				"classes": ""
			}
		},
		"name": "current-spark",
		"style": {
			"classes": ""
		},
		"header": {
			"style": {
				"classes": ""
			},
			"title": "",
			"enabled": false
		},
		"minSize": {
			"rowSpan": 2,
			"columnSpan": 2
		},
		"position": {
			"rowEnd": 4,
			"rowStart": 1,
			"columnEnd": 11,
			"columnStart": 6
		},
		"viewPath": "Exchange/Dashboard Agent/Dashboard Templates/sparkline",
		"viewParams": {
			"footer": "A - last 15 min",
			"header": "Drive current",
			"points": 60,
			"tagPath": "[default]Exchange/Alarm Flood/Site1/Area1/Line1/Packaging/MotorCurrent",
			"minutesBack": 15
		},
		"isConfigurable": false
	},
	{
		"body": {
			"style": {
				"classes": ""
			}
		},
		"name": "infeed-ring",
		"style": {
			"classes": ""
		},
		"header": {
			"style": {
				"classes": ""
			},
			"title": "",
			"enabled": false
		},
		"minSize": {
			"rowSpan": 2,
			"columnSpan": 2
		},
		"position": {
			"rowEnd": 4,
			"rowStart": 1,
			"columnEnd": 15,
			"columnStart": 11
		},
		"viewPath": "Exchange/Dashboard Agent/Dashboard Templates/ring",
		"viewParams": {
			"footer": "% full",
			"header": "Packaging infeed",
			"engHigh": 100,
			"tagPath": "[default]Exchange/Alarm Flood/Site1/Area1/Line1/Packaging/InfeedBufferLevel"
		},
		"isConfigurable": false
	},
	{
		"body": {
			"style": {
				"classes": ""
			}
		},
		"name": "flow-sankey",
		"style": {
			"classes": ""
		},
		"header": {
			"style": {
				"classes": ""
			},
			"title": "",
			"enabled": false
		},
		"minSize": {
			"rowSpan": 2,
			"columnSpan": 2
		},
		"position": {
			"rowEnd": 9,
			"rowStart": 4,
			"columnEnd": 9,
			"columnStart": 1
		},
		"viewPath": "Exchange/Dashboard Agent/Dashboard Templates/sankey",
		"viewParams": {
			"footer": "% of each station's nominal rate",
			"header": "Material flow",
			"linePath": ""
		},
		"isConfigurable": false
	},
	{
		"body": {
			"style": {
				"classes": ""
			}
		},
		"name": "rate-bars",
		"style": {
			"classes": ""
		},
		"header": {
			"style": {
				"classes": ""
			},
			"title": "",
			"enabled": false
		},
		"minSize": {
			"rowSpan": 2,
			"columnSpan": 2
		},
		"position": {
			"rowEnd": 9,
			"rowStart": 4,
			"columnEnd": 15,
			"columnStart": 9
		},
		"viewPath": "Exchange/Dashboard Agent/Dashboard Templates/station-bar",
		"viewParams": {
			"footer": "% of nominal throughput",
			"header": "Station rate",
			"metric": "rate",
			"linePath": ""
		},
		"isConfigurable": false
	},
	{
		"body": {
			"style": {
				"classes": ""
			}
		},
		"name": "alarm-heatmap",
		"style": {
			"classes": ""
		},
		"header": {
			"style": {
				"classes": ""
			},
			"title": "",
			"enabled": false
		},
		"minSize": {
			"rowSpan": 2,
			"columnSpan": 3
		},
		"position": {
			"rowEnd": 13,
			"rowStart": 9,
			"columnEnd": 15,
			"columnStart": 1
		},
		"viewPath": "Exchange/Dashboard Agent/Dashboard Templates/heatmap",
		"viewParams": {
			"footer": "Last 12 h, 30 min buckets",
			"header": "Alarm density",
			"linePath": "",
			"hoursBack": 12,
			"bucketMinutes": 30
		},
		"isConfigurable": false
	}
]
$json$ AS jsonb))) AS v(widgets_json)
), updated_at = now()
WHERE lower(name) = 'line overview'
	AND jsonb_array_length(widgets_json) = 8
	AND widgets_json @> CAST('[{"name": "throughput-funnel"}]' AS jsonb)
	AND widgets_json @> CAST('[{"name": "drive-area"}]' AS jsonb);
