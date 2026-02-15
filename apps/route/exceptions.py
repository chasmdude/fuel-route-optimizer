"""
Domain exceptions for the route optimization service.

These are raised by services and caught by views to produce
structured error responses. Keeping them in one file makes it
easy to see every failure mode the system handles.
"""


class GeocodingError(Exception):
    """Raised when a location string cannot be resolved to coordinates."""

    def __init__(self, location: str, detail: str = ""):
        self.location = location
        self.detail = detail
        super().__init__(f"Could not geocode location: '{location}'. {detail}".strip())


class RoutingError(Exception):
    """Raised when ORS cannot compute a driving route."""

    def __init__(self, detail: str = ""):
        self.detail = detail
        super().__init__(f"Routing failed. {detail}".strip())


class OptimizationError(Exception):
    """
    Raised when no valid fuel plan can be constructed.

    This typically means there is a gap > vehicle range between
    consecutive fuel stations along the route.
    """

    def __init__(self, detail: str = ""):
        self.detail = detail
        super().__init__(f"Fuel optimization failed. {detail}".strip())
