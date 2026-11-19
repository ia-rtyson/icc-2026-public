	# 20-minute feeder for the Designer Embeds demo table; all logic lives in
	# exchange.designerEmbeds.events.tick() -- insert one event, age acknowledgements, purge >7 days.
	# Gated by [default]Exchange/Demo/Control/Timers/DemoEventsFeederEnabled.
	exchange.designerEmbeds.events.tick()
