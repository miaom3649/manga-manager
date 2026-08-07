from hlibrary.api import create_api


def test_health_endpoint() -> None:
    app = create_api()
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/health")
    payload = route.endpoint()
    assert payload["status"] == "ok"
    assert payload["name"] == "H库"
