from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hmanga import __version__
from hmanga.catalog import CatalogQuery, CatalogService
from hmanga.i18n import available_languages, language_catalog, tr, trf
from hmanga.library import LibraryService
from hmanga.media import MediaService
from hmanga.pairing import PairingService


class PairRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    name: str = Field(default=tr("label.my_device"), max_length=200)


class WorkUpdate(BaseModel):
    title: str = Field(default="", max_length=1000)
    rating: int = Field(default=0, ge=0, le=3)
    tag_ids: list[int] = Field(default_factory=list)
    cover_member: str | None = Field(default=None, max_length=1024)


class ProgressUpdate(BaseModel):
    page_index: int = Field(ge=0)
    page_offset: int = Field(default=0, ge=0)
    fingerprint: str = Field(max_length=64)


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    group_id: int | None = None


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TagUpdate(TagCreate):
    pass


def create_api(
    web_root: Path | None = None,
    library: LibraryService | None = None,
    catalog: CatalogService | None = None,
    media: MediaService | None = None,
    pairing: PairingService | None = None,
) -> FastAPI:
    app = FastAPI(title=tr("label.lan_service"), version=__version__)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "name": "HManガ", "version": __version__}

    @app.get("/api/version")
    def version() -> dict[str, str]:
        return {"version": __version__}

    def authorize(authorization: str | None) -> None:
        if pairing is None:
            return
        prefix = "Bearer "
        token = (
            authorization[len(prefix) :]
            if authorization and authorization.startswith(prefix)
            else ""
        )
        if pairing.authenticate(token) is None:
            raise HTTPException(401, tr("label.device_not_paired"))

    @app.get("/api/state")
    def shared_state(authorization: str | None = Header(None)) -> dict[str, int]:
        authorize(authorization)
        unread = 0
        if catalog:
            from hmanga.notifications import NotificationService

            unread = NotificationService(catalog.database).unread_count()
        return {"revision": catalog.revision if catalog else 0, "unread": unread}

    @app.post("/api/pair")
    def pair(payload: PairRequest, request: Request) -> dict[str, str]:
        if pairing is None:
            raise HTTPException(503, tr("label.pairing_service_unavailable"))
        try:
            token = pairing.pair(
                payload.code,
                payload.name,
                request.headers.get("user-agent", ""),
                request.client.host if request.client else "unknown",
            )
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        return {"token": token}

    @app.delete("/api/devices/me")
    def disconnect_device(authorization: str | None = Header(None)) -> dict[str, str]:
        authorize(authorization)
        assert pairing is not None
        token = authorization.removeprefix("Bearer ") if authorization else ""
        pairing.revoke_token(token)
        return {"status": "ok"}

    @app.get("/api/devices/me")
    def current_device(authorization: str | None = Header(None)) -> dict[str, str]:
        authorize(authorization)
        assert pairing is not None
        token = authorization.removeprefix("Bearer ") if authorization else ""
        device = pairing.authenticate(token)
        assert device is not None
        return {"id": device.id, "name": device.name, "userAgent": device.user_agent}

    @app.get("/api/library/status")
    def library_status(authorization: str | None = Header(None)) -> dict[str, object]:
        authorize(authorization)
        import socket

        root = library.library_root() if library else None
        return {
            "configured": root is not None,
            "root": str(root) if root else None,
            "works": library.count_works() if library else 0,
            "computerName": socket.gethostname(),
        }

    @app.get("/api/locales")
    def locales(authorization: str | None = Header(None)) -> list[dict[str, str]]:
        authorize(authorization)
        return [{"code": code, "name": name} for code, name in available_languages()]

    @app.get("/api/locales/{code}")
    def locale_messages(code: str, authorization: str | None = Header(None)) -> dict[str, str]:
        authorize(authorization)
        try:
            return language_catalog(code)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/works")
    def works(
        text: str = "",
        page: int = Query(1, ge=1),
        sort: str = "added",
        descending: bool = True,
        kinds: str | None = None,
        tag_ids: str = "",
        tag_mode: str = "any",
        rating_mode: str = "any",
        rating: int = Query(0, ge=0, le=3),
        authorization: str | None = Header(None),
    ) -> dict[str, object]:
        authorize(authorization)
        if catalog is None:
            items = library.list_works() if library else []
            total, current_page, pages = len(items), 1, 1
        else:
            requested_kinds = tuple(value for value in (kinds or "").split(",") if value) or (
                "comic",
            )
            result = catalog.query(
                CatalogQuery(
                    text=text,
                    page=page,
                    sort_by=sort,
                    descending=descending,
                    kinds=requested_kinds,
                    tag_ids=tuple(int(value) for value in tag_ids.split(",") if value.isdigit()),
                    tag_mode=tag_mode,
                    rating_mode=rating_mode,
                    rating=rating,
                )
            )
            items, total = result.items, result.total
            current_page, pages = result.page, result.pages
        all_tags = catalog.list_tags() if catalog else []
        return {
            "items": [
                {
                    "id": item.id,
                    "kind": item.kind,
                    "fileName": item.file_name,
                    "number": item.number,
                    "title": item.title or Path(item.file_name).stem,
                    "rating": item.rating,
                    "status": item.status,
                    "coverVersion": f"{item.fingerprint}:{item.cover_member or ''}",
                    "tags": [
                        {
                            "id": tag.id,
                            "name": catalog.tag_display_name(tag, all_tags),
                            "groupId": tag.group_id,
                            "groupName": tag.group.name if tag.group else None,
                        }
                        for tag in item.tags
                    ]
                    if catalog
                    else [],
                }
                for item in items
            ],
            "total": total,
            "page": current_page,
            "pages": pages,
        }

    @app.get("/api/works/{work_id}/thumbnail")
    def thumbnail(work_id: int, authorization: str | None = Header(None)):
        authorize(authorization)
        if catalog is None or media is None:
            raise HTTPException(503, tr("label.media_service_unavailable"))
        work = catalog.get_work(work_id)
        if work is None:
            raise HTTPException(404, tr("error.work_not_found"))
        try:
            return FileResponse(media.thumbnail(work))
        except (OSError, KeyError) as exc:
            raise HTTPException(422, trf("error.cover_read", error=exc)) from exc

    @app.get("/api/works/{work_id}")
    def work_detail(work_id: int, authorization: str | None = Header(None)) -> dict[str, object]:
        authorize(authorization)
        if catalog is None:
            raise HTTPException(503, tr("label.work_service_unavailable"))
        work = catalog.get_work(work_id)
        if work is None:
            raise HTTPException(404, tr("error.work_not_found"))
        all_tags = catalog.list_tags()
        return {
            "id": work.id,
            "kind": work.kind,
            "fileName": work.file_name,
            "number": work.number,
            "title": work.title or Path(work.file_name).stem,
            "rating": work.rating,
            "fingerprint": work.fingerprint,
            "coverMember": work.cover_member,
            "coverVersion": f"{work.fingerprint}:{work.cover_member or ''}",
            "tags": [
                {
                    "id": tag.id,
                    "name": catalog.tag_display_name(tag, all_tags),
                    "groupId": tag.group_id,
                    "groupName": tag.group.name if tag.group else None,
                }
                for tag in work.tags
            ],
            "previews": media.preview_members(work) if media and work.kind == "comic" else [],
        }

    @app.put("/api/works/{work_id}")
    def update_work(
        work_id: int,
        payload: WorkUpdate,
        authorization: str | None = Header(None),
    ) -> dict[str, str]:
        authorize(authorization)
        if catalog is None:
            raise HTTPException(503, tr("label.work_service_unavailable"))
        work = catalog.get_work(work_id)
        if work is None:
            raise HTTPException(404, tr("error.work_not_found"))
        if work.kind == "comic" and payload.cover_member and media:
            if payload.cover_member not in media.comic_members(work):
                raise HTTPException(422, tr("error.selected_cover_missing"))
        try:
            catalog.update_work(
                work_id,
                title=payload.title,
                rating=payload.rating,
                tag_ids=payload.tag_ids,
                cover_member=payload.cover_member,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"status": "ok"}

    @app.get("/api/tags")
    def tags(search: str = "", authorization: str | None = Header(None)) -> list[dict[str, object]]:
        authorize(authorization)
        if catalog is None:
            return []
        all_tags = catalog.list_tags()
        return [
            {
                "id": tag.id,
                "name": catalog.tag_display_name(tag, all_tags),
                "rawName": tag.name,
                "groupId": tag.group_id,
                "groupName": tag.group.name if tag.group else None,
                "works": len(tag.works),
            }
            for tag in catalog.list_tags(search)
        ]

    @app.post("/api/tags")
    def create_tag(
        payload: TagCreate, authorization: str | None = Header(None)
    ) -> dict[str, object]:
        authorize(authorization)
        if catalog is None:
            raise HTTPException(503, tr("label.tag_service_unavailable"))
        try:
            tag = catalog.create_tag(payload.name, payload.group_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"id": tag.id, "name": tag.name}

    @app.get("/api/tag-groups")
    def tag_groups(authorization: str | None = Header(None)) -> list[dict[str, object]]:
        authorize(authorization)
        if catalog is None:
            return []
        results = []
        for group in catalog.list_groups():
            comics, illustrations = catalog.group_impact(group.id)
            results.append(
                {
                    "id": group.id,
                    "name": group.name,
                    "tags": len(group.tags),
                    "comics": comics,
                    "illustrations": illustrations,
                    "system": catalog.is_system_group(group),
                }
            )
        return results

    @app.post("/api/tag-groups")
    def create_group(
        payload: GroupCreate, authorization: str | None = Header(None)
    ) -> dict[str, object]:
        authorize(authorization)
        if catalog is None:
            raise HTTPException(503, tr("label.tag_service_unavailable"))
        try:
            group = catalog.create_group(payload.name)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"id": group.id, "name": group.name}

    @app.put("/api/tags/{tag_id}")
    def update_tag(
        tag_id: int,
        payload: TagUpdate,
        authorization: str | None = Header(None),
    ) -> dict[str, str]:
        authorize(authorization)
        if catalog is None:
            raise HTTPException(503, tr("label.tag_service_unavailable"))
        try:
            catalog.edit_tag(tag_id, payload.name, payload.group_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"status": "ok"}

    @app.delete("/api/tags/{tag_id}")
    def remove_tag(tag_id: int, authorization: str | None = Header(None)) -> dict[str, int]:
        authorize(authorization)
        if catalog is None:
            raise HTTPException(503, tr("label.tag_service_unavailable"))
        try:
            affected = catalog.delete_tag(tag_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"affected": affected}

    @app.put("/api/tag-groups/{group_id}")
    def update_group(
        group_id: int,
        payload: GroupCreate,
        authorization: str | None = Header(None),
    ) -> dict[str, str]:
        authorize(authorization)
        if catalog is None:
            raise HTTPException(503, tr("label.tag_service_unavailable"))
        try:
            catalog.rename_group(group_id, payload.name)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"status": "ok"}

    @app.delete("/api/tag-groups/{group_id}")
    def remove_group(
        group_id: int,
        delete_tags: bool = False,
        authorization: str | None = Header(None),
    ) -> dict[str, int]:
        authorize(authorization)
        if catalog is None:
            raise HTTPException(503, tr("label.tag_service_unavailable"))
        try:
            comics, illustrations = catalog.delete_group(group_id, delete_tags)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"comics": comics, "illustrations": illustrations}

    @app.get("/api/works/{work_id}/pages")
    def pages(work_id: int, authorization: str | None = Header(None)) -> dict[str, object]:
        authorize(authorization)
        if catalog is None or media is None:
            raise HTTPException(503, tr("label.media_service_unavailable"))
        work = catalog.get_work(work_id)
        if work is None or work.kind != "comic":
            raise HTTPException(404, tr("error.comic_not_found"))
        return {"items": media.comic_members(work), "fingerprint": work.fingerprint}

    @app.get("/api/works/{work_id}/previews/{preview_index}")
    def preview_image(
        work_id: int,
        preview_index: int,
        authorization: str | None = Header(None),
    ):
        authorize(authorization)
        if catalog is None or media is None:
            raise HTTPException(503, tr("label.media_service_unavailable"))
        work = catalog.get_work(work_id)
        if work is None:
            raise HTTPException(404, tr("error.work_not_found"))
        previews = media.preview_members(work)
        if preview_index < 0 or preview_index >= len(previews):
            raise HTTPException(404, tr("error.preview_not_found"))
        from fastapi.responses import Response

        return Response(media.read_original(work, previews[preview_index]), media_type="image/webp")

    @app.get("/api/works/{work_id}/pages/{page_index}")
    def page_image(work_id: int, page_index: int, authorization: str | None = Header(None)):
        authorize(authorization)
        if catalog is None or media is None:
            raise HTTPException(503, tr("label.media_service_unavailable"))
        work = catalog.get_work(work_id)
        if work is None or work.kind != "comic":
            raise HTTPException(404, tr("error.comic_not_found"))
        members = media.comic_members(work)
        if page_index < 0 or page_index >= len(members):
            raise HTTPException(404, tr("error.page_not_found"))
        try:
            data = media.read_original(work, members[page_index])
        except (OSError, KeyError) as exc:
            raise HTTPException(422, trf("error.page_read", error=exc)) from exc
        from fastapi.responses import Response

        return Response(data, media_type="image/webp")

    @app.delete("/api/works/{work_id}")
    def delete_work(work_id: int, authorization: str | None = Header(None)) -> dict[str, str]:
        authorize(authorization)
        if library is None or catalog is None or media is None:
            raise HTTPException(503, tr("label.work_service_unavailable"))
        work = catalog.get_work(work_id)
        if work is None:
            raise HTTPException(404, tr("error.work_not_found"))
        root = library.library_root()
        if root is None:
            raise HTTPException(409, tr("label.library_root_unset"))
        root = root.resolve()
        path = media.work_path(work).resolve()
        if not path.is_relative_to(root):
            raise HTTPException(403, tr("label.work_outside_library"))
        if not path.is_file():
            raise HTTPException(404, trf("error.file_missing", file_name=work.file_name))
        try:
            # Do not let an already-running directory scan commit a stale copy
            # of this work after the phone has deleted it.
            with library.operation_lock:
                path.unlink()
                catalog.delete_work(work.id)
                media.clear_thumbnail_cache()
        except OSError as exc:
            raise HTTPException(409, trf("error.delete", error=exc)) from exc
        return {"status": "ok"}

    @app.get("/api/works/{work_id}/progress")
    def get_progress(work_id: int, authorization: str | None = Header(None)) -> dict[str, object]:
        authorize(authorization)
        if catalog is None or media is None:
            raise HTTPException(503, tr("label.reader_service_unavailable"))
        work = catalog.get_work(work_id)
        if work is None:
            raise HTTPException(404, tr("error.work_not_found"))
        from hmanga.reader import ReaderService

        value = ReaderService(catalog.database, media).progress(work)
        return {
            "pageIndex": value.page_index if value else 0,
            "pageOffset": value.page_offset if value else 0,
            "hasProgress": value is not None,
            "fingerprint": work.fingerprint,
        }

    @app.put("/api/works/{work_id}/progress")
    def save_progress(
        work_id: int,
        payload: ProgressUpdate,
        authorization: str | None = Header(None),
    ) -> dict[str, str]:
        authorize(authorization)
        if catalog is None or media is None:
            raise HTTPException(503, tr("label.reader_service_unavailable"))
        work = catalog.get_work(work_id)
        if work is None:
            raise HTTPException(404, tr("error.work_not_found"))
        if payload.fingerprint != (work.fingerprint or ""):
            raise HTTPException(409, tr("message.replacement_progress_not_synced"))
        from hmanga.reader import ReaderService

        current = ReaderService(catalog.database, media).progress(work)
        page_index = max(payload.page_index, current.page_index if current else 0)
        if current and payload.page_index < current.page_index:
            page_offset = current.page_offset
        elif current and payload.page_index == current.page_index:
            page_offset = max(payload.page_offset, current.page_offset)
        else:
            page_offset = payload.page_offset
        ReaderService(catalog.database, media).save_progress(work, page_index, page_offset)
        return {"status": "ok"}

    @app.get("/api/notifications")
    def notifications(authorization: str | None = Header(None)) -> dict[str, object]:
        authorize(authorization)
        if library is None or catalog is None:
            return {"items": [], "unread": 0}
        from hmanga.notifications import NotificationService

        service = NotificationService(catalog.database)
        return {
            "items": [
                {
                    "id": item.id,
                    "kind": item.kind,
                    "title": item.title,
                    "details": item.details_json,
                    "createdAt": item.created_at.isoformat(),
                    "read": item.read_at is not None,
                }
                for item in library.list_notifications()
            ],
            "unread": service.unread_count(),
        }

    @app.post("/api/notifications/read")
    def read_notifications(authorization: str | None = Header(None)) -> dict[str, str]:
        authorize(authorization)
        if catalog:
            from hmanga.notifications import NotificationService

            NotificationService(catalog.database).mark_all_read()
        return {"status": "ok"}

    @app.get("/api/replacements")
    def replacements(authorization: str | None = Header(None)) -> list[dict[str, object]]:
        authorize(authorization)
        if library is None:
            return []
        return [
            {"workId": work.id, "fileName": work.file_name}
            for work in library.pending_replacements()
        ]

    @app.post("/api/replacements/{work_id}")
    def resolve_replacement(
        work_id: int,
        preserve_metadata: bool,
        authorization: str | None = Header(None),
    ) -> dict[str, str]:
        authorize(authorization)
        if library is None:
            raise HTTPException(503, tr("label.work_service_unavailable"))
        try:
            library.resolve_replacement(work_id, preserve_metadata)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"status": "ok"}

    @app.delete("/api/notifications/all")
    def clear_notifications(authorization: str | None = Header(None)) -> dict[str, str]:
        authorize(authorization)
        if catalog:
            from hmanga.notifications import NotificationService

            NotificationService(catalog.database).clear()
        return {"status": "ok"}

    @app.delete("/api/notifications/{notification_id}")
    def delete_notification(
        notification_id: int, authorization: str | None = Header(None)
    ) -> dict[str, str]:
        authorize(authorization)
        if catalog:
            from hmanga.notifications import NotificationService

            NotificationService(catalog.database).delete(notification_id)
        return {"status": "ok"}

    if web_root is not None and (web_root / "index.html").exists():
        web_root = web_root.resolve()
        assets = web_root / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        def web_app(full_path: str):
            candidate = (web_root / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(web_root):
                return FileResponse(candidate)
            return FileResponse(web_root / "index.html")

    else:

        @app.get("/", response_class=HTMLResponse)
        def placeholder() -> str:
            return f"""
            <!doctype html><html lang="zh-CN"><meta charset="utf-8">
            <meta name="viewport" content="width=device-width,initial-scale=1">
            <title>HManガ</title><body style="font-family:sans-serif;padding:2rem">
            <h1>HManガ</h1><p>{tr("web.unbuilt")}</p></body></html>
            """

    return app
