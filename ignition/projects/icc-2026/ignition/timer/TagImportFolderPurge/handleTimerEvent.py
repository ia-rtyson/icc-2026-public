	# Demo reset: empties both Exchange/Tag Import Agent roots (the tag folder and
	# the _types_ UDT-definition folder) 10 minutes after the agent created them.
	# purgeDemoFolder() owns the age check and is a no-op on every other tick.
	# Gated by [default]Exchange/Demo/Control/Timers/TagImportFolderPurgeEnabled,
	# which fails closed (a destructive timer does not run on an unreadable switch).
	exchange.tagImport.core.purgeDemoFolder()
