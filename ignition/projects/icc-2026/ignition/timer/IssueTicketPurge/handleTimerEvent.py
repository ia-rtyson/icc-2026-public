	# Nightly demo reset: deletes every ticket in the YouTrack UI project on the
	# first tick of each new local day. Polls every 10 minutes because gateway
	# event scripts have no cron; purgeTickets() owns the once-a-day decision and
	# is a no-op on every other tick. Inert when YOUTRACK_TOKEN is unset, and when
	# the [default]Exchange/Demo/Control/Timers/IssueTicketPurgeEnabled switch is off or
	# unreadable (a destructive timer fails closed).
	exchange.issueReport.pipeline.purgeTickets()
