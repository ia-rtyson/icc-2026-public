	# Housekeeping for the Dashboard Agent save/load feature. Deletes every saved
	# dashboard that is not flagged is_demo once the day it was last touched has
	# passed, so the demo environment is clean each morning.
	#
	# 15 minutes rather than 24 hours because gateway event scripts have no cron:
	# a fixed-delay timer restarts from gateway start, so a daily timer would
	# drift to whatever time the gateway last came up. Polling for the date
	# rollover is what keeps the sweep pinned to just after midnight.
	#
	# Gated by [default]Exchange/Demo/Control/Timers/DashboardConfigPurgeEnabled, which
	# fails closed (a destructive timer does not run on an unreadable switch).
	exchange.dashboard.configs.purgeStale()
