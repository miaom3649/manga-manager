from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hlibrary import __version__
from hlibrary.catalog import CatalogQuery, CatalogService
from hlibrary.library import LibraryService
from hlibrary.media import MediaService
from hlibrary.pairing import PairingService
from hlibrary.upload import UploadService, UploadTask


class PairRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    nonce: str = Field(min_length=16, max_length=200)
    name: str = Field(default="我的设备", max_length=200)


class WorkUpdate(BaseModel):
    title: str = Field(default="", max_length=1000)
    rating: int = Field(default=0, ge=0, le=3)
    tag_ids: list[int] = Field(default_factory=list)
    cover_member: str | None = Field(default=None, max_length=1024)


class ProgressUpdate(BaseModel):
    page_index: int = Field(ge=0)
    page_offset: int = Field(default=0, ge=0)
    fingerprint: str = Field(max_length=64)


class UploadMetadata(BaseModel):
    title: str = Field(default="", max_length=1000)
    rating: int = Field(default=0, ge=0, le=3)
    tag_ids: list[int] = Field(default_factory=list)
    cover_member: str | None = Field(default=None, max_length=1024)
    removed: bool = False


class UploadCommit(BaseModel):
    allow_overwrite: bool = False
    items: list[UploadMetadata]


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
    uploads: UploadService | None = None,
) -> FastAPI:
    app = FastAPI(title="H库局域网服务", version=__version__)
    upload_tasks: dict[str, UploadTask] = {}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "name": "H库", "version": __version__}

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
            raise HTTPException(401, "设备尚未配对")

    @app.post("/api/pair")
    def pair(payload: PairRequest, request: Request) -> dict[str, str]:
        if pairing is None:
            raise HTTPException(503, "配对服务尚未启用")
        try:
            token = pairing.pair(
                payload.code,
                payload.nonce,
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

    @app.get("/api/works")
    def works(
        text: str = "",
        page: int = Query(1, ge=1),
        sort: str = "added",
        descending: bool = True,
        kinds: str = "",
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
            result = catalog.query(
                CatalogQuery(
                    text=text,
                    page=page,
                    sort_by=sort,
                    descending=descending,
                    kinds=tuple(value for value in kinds.split(",") if value),
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
                    "tags": [
                        {"id": tag.id, "name": catalog.tag_display_name(tag, all_tags)}
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
            raise HTTPException(503, "媒体服务尚未启用")
        work = catalog.get_work(work_id)
        if work is None:
            raise HTTPException(404, "作品不存在")
        try:
            return FileResponse(media.thumbnail(work))
        except (OSError, KeyError) as exc:
            raise HTTPException(422, f"封面无法读取：{exc}") from exc

    @app.get("/api/works/{work_id}")
    def work_detail(work_id: int, authorization: str | None = Header(None)) -> dict[str, object]:
        authorize(authorization)
        if catalog is None:
            raise HTTPException(503, "作品服务尚未启用")
        work = catalog.get_work(work_id)
        if work is None:
            raise HTTPException(404, "作品不存在")
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
            "tags": [
                {"id": tag.id, "name": catalog.tag_display_name(tag, all_tags)} for tag in work.tags
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
            raise HTTPException(503, "作品服务尚未启用")
        work = catalog.get_work(work_id)
        if work is None:
            raise HTTPException(404, "作品不存在")
        if work.kind == "comic" and payload.cover_member and media:
            if payload.cover_member not in media.comic_members(work):
                raise HTTPException(422, "所选封面不存在")
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
            raise HTTPException(503, "Tag 服务尚未启用")
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
                }
            )
        return results

    @app.post("/api/tag-groups")
    def create_group(
        payload: GroupCreate, authorization: str | None = Header(None)
    ) -> dict[str, object]:
        authorize(authorization)
        if catalog is None:
            raise HTTPException(503, "Tag 服务尚未启用")
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
            raise HTTPException(503, "Tag 服务尚未启用")
        try:
            catalog.rename_tag(tag_id, payload.name)
            catalog.move_tag(tag_id, payload.group_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"status": "ok"}

    @app.delete("/api/tags/{tag_id}")
    def remove_tag(tag_id: int, authorization: str | None = Header(None)) -> dict[str, int]:
        authorize(authorization)
        if catalog is None:
            raise HTTPException(503, "Tag 服务尚未启用")
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
            raise HTTPException(503, "Tag 服务尚未启用")
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
            raise HTTPException(503, "Tag 服务尚未启用")
        try:
            comics, illustrations = catalog.delete_group(group_id, delete_tags)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"comics": comics, "illustrations": illustrations}

    @app.get("/api/works/{work_id}/pages")
    def pages(work_id: int, authorization: str | None = Header(None)) -> dict[str, object]:
        authorize(authorization)
        if catalog is None or media is None:
            raise HTTPException(503, "媒体服务尚未启用")
        work = catalog.get_work(work_id)
        if work is None or work.kind != "comic":
            raise HTTPException(404, "漫画不存在")
        return {"items": media.comic_members(work), "fingerprint": work.fingerprint}

    @app.get("/api/works/{work_id}/previews/{preview_index}")
    def preview_image(
        work_id: int,
        preview_index: int,
        authorization: str | None = Header(None),
    ):
        authorize(authorization)
        if catalog is None or media is None:
            raise HTTPException(503, "媒体服务尚未启用")
        work = catalog.get_work(work_id)
        if work is None:
            raise HTTPException(404, "作品不存在")
        previews = media.preview_members(work)
        if preview_index < 0 or preview_index >= len(previews):
            raise HTTPException(404, "预览图不存在")
        from fastapi.responses import Response

        return Response(media.read_original(work, previews[preview_index]), media_type="image/webp")

    @app.get("/api/works/{work_id}/pages/{page_index}")
    def page_image(work_id: int, page_index: int, authorization: str | None = Header(None)):
        authorize(authorization)
        if catalog is None or media is None:
            raise HTTPException(503, "媒体服务尚未启用")
        work = catalog.get_work(work_id)
        if work is None or work.kind != "comic":
            raise HTTPException(404, "漫画不存在")
        members = media.comic_members(work)
        if page_index < 0 or page_index >= len(members):
            raise HTTPException(404, "页码不存在")
        try:
            data = media.read_original(work, members[page_index])
        except (OSError, KeyError) as exc:
            raise HTTPException(422, f"页面无法读取：{exc}") from exc
        from fastapi.responses import Response

        return Response(data, media_type="image/webp")

    @app.get("/api/works/{work_id}/progress")
    def get_progress(work_id: int, authorization: str | None = Header(None)) -> dict[str, object]:
        authorize(authorization)
        if catalog is None or media is None:
            raise HTTPException(503, "阅读服务尚未启用")
        work = catalog.get_work(work_id)
        if work is None:
            raise HTTPException(404, "作品不存在")
        from hlibrary.reader import ReaderService

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
            raise HTTPException(503, "阅读服务尚未启用")
        work = catalog.get_work(work_id)
        if work is None:
            raise HTTPException(404, "作品不存在")
        if payload.fingerprint != (work.fingerprint or ""):
            raise HTTPException(409, "作品内容已被替换，旧阅读进度不能同步")
        from hlibrary.reader import ReaderService

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

    @app.post("/api/uploads")
    async def prepare_upload(
        files: list[UploadFile] = File(...),  # noqa: B008 - FastAPI dependency
        authorization: str | None = Header(None),
    ) -> dict[str, object]:
        authorize(authorization)
        if uploads is None:
            raise HTTPException(503, "上传服务尚未启用")
        import tempfile

        source_directory = Path(tempfile.mkdtemp(prefix="hlibrary-mobile-upload-"))
        sources = []
        try:
            for index, upload in enumerate(files):
                safe_name = Path(upload.filename or f"upload-{index}").name
                item_directory = source_directory / f"{index:04d}"
                item_directory.mkdir()
                target = item_directory / safe_name
                with target.open("wb") as output:
                    while chunk := await upload.read(1024 * 1024):
                        output.write(chunk)
                sources.append(target)
            task = uploads.prepare(sources)
        finally:
            import shutil

            shutil.rmtree(source_directory, ignore_errors=True)
        upload_tasks[task.id] = task
        return {
            "taskId": task.id,
            "items": [
                {
                    "name": item.source.name,
                    "kind": item.kind,
                    "valid": item.valid,
                    "error": item.error,
                    "conflict": item.conflict,
                    "title": item.title,
                    "rating": item.rating,
                    "coverMember": item.cover_member,
                }
                for item in task.items
            ],
        }

    @app.post("/api/uploads/{task_id}/commit")
    def commit_upload(
        task_id: str,
        payload: UploadCommit,
        authorization: str | None = Header(None),
    ) -> dict[str, object]:
        authorize(authorization)
        if uploads is None or (task := upload_tasks.get(task_id)) is None:
            raise HTTPException(404, "上传任务不存在或已结束")
        if len(payload.items) != len(task.items):
            raise HTTPException(422, "上传资料数量不一致")
        kept = []
        for item, metadata in zip(task.items, payload.items, strict=True):
            if metadata.removed:
                item.staged.unlink(missing_ok=True)
                continue
            item.title = metadata.title
            item.rating = metadata.rating
            item.tag_ids = set(metadata.tag_ids)
            item.cover_member = metadata.cover_member or item.cover_member
            kept.append(item)
        task.items = kept
        if not task.items:
            raise HTTPException(422, "上传任务中没有文件")
        try:
            work_ids = uploads.commit(task, payload.allow_overwrite)
        except (ValueError, FileExistsError) as exc:
            raise HTTPException(409, str(exc)) from exc
        finally:
            upload_tasks.pop(task_id, None)
        return {"status": "ok", "workIds": work_ids}

    def upload_members(task_id: str, item_index: int) -> tuple[UploadTask, list[str]]:
        import zipfile

        from hlibrary.media import IMAGE_SUFFIXES
        from hlibrary.text import natural_key

        task = upload_tasks.get(task_id)
        if task is None or item_index < 0 or item_index >= len(task.items):
            raise HTTPException(404, "上传项不存在")
        item = task.items[item_index]
        if item.kind != "comic":
            raise HTTPException(422, "只有漫画可以选择压缩包内封面")
        with zipfile.ZipFile(item.staged) as archive:
            members = sorted(
                [
                    info.filename
                    for info in archive.infolist()
                    if not info.is_dir() and Path(info.filename).suffix.casefold() in IMAGE_SUFFIXES
                ],
                key=natural_key,
            )
        return task, members

    @app.get("/api/uploads/{task_id}/items/{item_index}/pages")
    def upload_pages(
        task_id: str, item_index: int, authorization: str | None = Header(None)
    ) -> dict[str, object]:
        authorize(authorization)
        _task, members = upload_members(task_id, item_index)
        return {"items": members}

    @app.get("/api/uploads/{task_id}/items/{item_index}/pages/{page_index}")
    def upload_page_image(
        task_id: str,
        item_index: int,
        page_index: int,
        authorization: str | None = Header(None),
    ):
        authorize(authorization)
        import zipfile

        from fastapi.responses import Response

        task, members = upload_members(task_id, item_index)
        if page_index < 0 or page_index >= len(members):
            raise HTTPException(404, "上传图片不存在")
        with zipfile.ZipFile(task.items[item_index].staged) as archive:
            return Response(archive.read(members[page_index]), media_type="image/webp")

    @app.delete("/api/uploads/{task_id}")
    def cancel_upload(task_id: str, authorization: str | None = Header(None)) -> dict[str, str]:
        authorize(authorization)
        if uploads and (task := upload_tasks.pop(task_id, None)):
            uploads.cancel(task)
        return {"status": "ok"}

    @app.get("/api/notifications")
    def notifications(authorization: str | None = Header(None)) -> dict[str, object]:
        authorize(authorization)
        if library is None or catalog is None:
            return {"items": [], "unread": 0}
        from hlibrary.notifications import NotificationService

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
            from hlibrary.notifications import NotificationService

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
            raise HTTPException(503, "作品服务尚未启用")
        try:
            library.resolve_replacement(work_id, preserve_metadata)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"status": "ok"}

    @app.delete("/api/notifications/all")
    def clear_notifications(authorization: str | None = Header(None)) -> dict[str, str]:
        authorize(authorization)
        if catalog:
            from hlibrary.notifications import NotificationService

            NotificationService(catalog.database).clear()
        return {"status": "ok"}

    @app.delete("/api/notifications/{notification_id}")
    def delete_notification(
        notification_id: int, authorization: str | None = Header(None)
    ) -> dict[str, str]:
        authorize(authorization)
        if catalog:
            from hlibrary.notifications import NotificationService

            NotificationService(catalog.database).delete(notification_id)
        return {"status": "ok"}

    @app.get("/api/events")
    async def events(request: Request, authorization: str | None = Header(None)):
        authorize(authorization)

        async def stream():
            import asyncio
            import json

            last_count = -1
            while not await request.is_disconnected():
                count = 0
                if catalog:
                    from hlibrary.notifications import NotificationService

                    count = NotificationService(catalog.database).unread_count()
                if count != last_count:
                    yield f"event: notifications\ndata: {json.dumps({'unread': count})}\n\n"
                    last_count = count
                await asyncio.sleep(2)

        return StreamingResponse(stream(), media_type="text/event-stream")

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
            return """
            <!doctype html><html lang="zh-CN"><meta charset="utf-8">
            <meta name="viewport" content="width=device-width,initial-scale=1">
            <title>H库</title><body style="font-family:sans-serif;padding:2rem">
            <h1>H库</h1><p>手机网页尚未构建，局域网服务运行正常。</p></body></html>
            """

    return app
