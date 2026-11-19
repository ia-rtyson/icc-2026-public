	# Every minute: maybe fabricate a downtime event or two on one of the five
	# Alarm Flood stations, then purge anything past exchange.demo.downtime's
	# retention window. All logic lives in exchange.demo.downtime.tick(), which also
	# checks the [default]Exchange/Demo/Control/Timers/EquipmentDowntimeFeederEnabled switch.
	exchange.demo.downtime.tick()
