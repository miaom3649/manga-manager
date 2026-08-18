from PIL import Image

from hmanga.api import create_api
from hmanga.catalog import CatalogQuery, CatalogService
from hmanga.database import Database
from hmanga.library import LibraryService
from hmanga.media import MediaService


def test_health_endpoint() -> None:
    app = create_api()
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/health")
    payload = route.endpoint()
    assert payload["status"] == "ok"
    assert payload["name"] == "HManガ"


def test_shared_state_endpoint_has_revision() -> None:
    app = create_api()
    route = next(route for route in app.routes if getattr(route, "path", None) == "/api/state")

    assert route.endpoint()["revision"] == 0


def test_mobile_locale_endpoints_expose_language_pack() -> None:
    app = create_api()
    list_route = next(
        route for route in app.routes if getattr(route, "path", None) == "/api/locales"
    )
    pack_route = next(
        route for route in app.routes if getattr(route, "path", None) == "/api/locales/{code}"
    )

    assert any(item["code"] == "zh-CN" and item["name"] for item in list_route.endpoint())
    assert "label.interface_language" in pack_route.endpoint("zh-CN")


def test_phone_delete_removes_file_record_and_updates_revision(tmp_path) -> None:
    database = Database(tmp_path / "main.db")
    database.initialize("test")
    library = LibraryService(database)
    root = library.configure_root(tmp_path / "library")
    source = root / "illustration" / "delete-me.png"
    Image.new("RGB", (12, 18), "navy").save(source)
    library.scan()
    catalog = CatalogService(database)
    media = MediaService(library, tmp_path / "cache")
    work = catalog.query(CatalogQuery(kinds=("illustration",))).items[0]
    revision = catalog.revision

    app = create_api(library=library, catalog=catalog, media=media)
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/works/{work_id}"
        and "DELETE" in getattr(route, "methods", set())
    )
    response = route.endpoint(work.id)

    assert response == {"status": "ok"}
    assert not source.exists()
    assert catalog.get_work(work.id) is None
    assert catalog.revision == revision + 1
