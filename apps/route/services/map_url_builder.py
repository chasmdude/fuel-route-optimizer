"""
Map URL builder.

Constructs a shareable OpenRouteService Maps URL that displays the
driving route with fuel stop waypoints. The URL opens an interactive
map -- no frontend code required.

URL format documented at:
https://ask.openrouteservice.org/t/supported-directions-url-parameters/1698
"""

from apps.route.dataclasses import Coordinates, SelectedStop


class MapURLBuilder:
    """
    Builds a clickable ORS map URL from route endpoints and fuel stops.
    """

    BASE_URL = "https://maps.openrouteservice.org/directions"

    def build_url(
        self,
        start: Coordinates,
        end: Coordinates,
        stops: list[SelectedStop] | None = None,
    ) -> str:
        """
        Construct an ORS map URL with start, end, and waypoints.

        The `a` parameter takes comma-separated lat,lon pairs for
        all waypoints in order: start, fuel stops, end.

        Args:
            start: Starting coordinates.
            end: Ending coordinates.
            stops: Optional list of fuel stops to include as waypoints.

        Returns:
            A full URL string that opens the route on ORS Maps.
        """
        waypoints = [start]

        if stops:
            for stop in stops:
                waypoints.append(Coordinates(lat=stop.lat, lon=stop.lon))

        waypoints.append(end)

        # Build the 'a' parameter: lat1,lon1,lat2,lon2,...
        a_param = ",".join(
            f"{wp.lat},{wp.lon}" for wp in waypoints
        )

        return (
            f"{self.BASE_URL}"
            f"?n1={start.lat}&n2={start.lon}&n3=6"
            f"&a={a_param}"
            f"&b=0&c=0&k1=en-US&k2=mi"
        )
