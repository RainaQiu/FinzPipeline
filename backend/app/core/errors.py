class ConfigurationError(ValueError):
    """Raised when a required configuration value is absent."""

    def __init__(self, missing_names: tuple[str, ...]) -> None:
        self.missing_names = missing_names
        super().__init__("Missing required environment variables: " + ", ".join(missing_names))
