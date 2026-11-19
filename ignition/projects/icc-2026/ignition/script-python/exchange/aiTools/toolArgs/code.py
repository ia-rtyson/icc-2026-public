"""Argument coercion for the AI agent tool bundles.

A tool's arguments are chosen by a model, so "12", 12, 12.0, "abc", "null" and
None all arrive for the same INTEGER parameter. A bare int() on that input
raised out of the tool, and the model saw a Java-flavoured stack message rather
than something it could correct. These helpers turn a bad value into an
ArgumentError, and invalidArgument() turns that into the structured payload the
tools return instead.
"""

logger = system.util.getLogger("exchange.aiTools.ToolArgs")

# Values a model uses to mean "not supplied"
_BLANKS = ("", "none", "null")
_TRUTHY = ("1", "true", "yes", "y")


class ArgumentError(ValueError):
	"""A tool argument that could not be coerced to the type it needs."""

	def __init__(self, name, value, expected):
		"""Build the error.

		Args:
			name (str): The tool parameter name, e.g. event_id.
			value (object): The value that was supplied.
			expected (str): What was wanted, e.g. "an integer".
		"""
		ValueError.__init__(self, "%s must be %s, got %s." % (name, expected, repr(value)))
		self.name = name
		self.value = value
		self.expected = expected


def isBlank(value):
	"""Return True when a model-supplied value means "not supplied".

	Args:
		value (object): The raw argument.

	Returns:
		bool: True for None, an empty string, "None" or "null".
	"""
	return value is None or unicode(value).strip().lower() in _BLANKS


def optionalInt(value, name, default=None):
	"""Coerce an optional integer argument.

	Args:
		value (object): The raw argument. Accepts ints, whole floats and
			numeric strings such as "12" or "12.0".
		name (str): The parameter name, used in the error message.
		default (int): Returned when the value is blank.

	Returns:
		int: The coerced value, or default when blank.

	Raises:
		ArgumentError: If the value is present but not a whole number.
	"""
	if isBlank(value):
		return default
	if isinstance(value, bool):
		raise ArgumentError(name, value, "an integer")
	if isinstance(value, (int, long)):
		return int(value)
	text = unicode(value).strip()
	try:
		return int(text)
	except:
		pass
	try:
		number = float(text)
		if number == int(number):
			return int(number)
	except:
		pass
	raise ArgumentError(name, value, "an integer")


def isTrue(value):
	"""Interpret a model-supplied boolean.

	Args:
		value (object): True, or a string such as "true", "yes" or "1".

	Returns:
		bool: True only for an affirmative value.
	"""
	return value is True or unicode(value).strip().lower() in _TRUTHY


def invalidArgument(error, toolName=None):
	"""Build the structured payload a tool returns for a bad argument.

	Also logs it, so a model that keeps sending a bad value is visible in the
	gateway log and not only in the chat.

	Args:
		error (ArgumentError): The coercion failure.
		toolName (str): The tool that received it, for the log line.

	Returns:
		dict: {status: "invalid_argument", argument, error}.
	"""
	logger.warn("%s: invalid argument %s" % (toolName or "tool", unicode(error)))
	return {
		"status": "invalid_argument",
		"argument": error.name,
		"error": unicode(error),
	}
