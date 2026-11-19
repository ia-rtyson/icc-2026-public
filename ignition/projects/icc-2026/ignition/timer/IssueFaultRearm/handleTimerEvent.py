	# Puts the Report Issue demo defect back 8 minutes after the pipeline fixes
	# it, so the demo re-stages itself and the page needs no operator buttons.
	# A no-op on every tick where the fault is already armed or the clear is
	# still inside the window -- see exchange.issueReport.report.rearmDemoFault, which also checks
	# the [default]Exchange/Demo/Control/Timers/IssueFaultRearmEnabled switch.
	exchange.issueReport.report.rearmDemoFault()
