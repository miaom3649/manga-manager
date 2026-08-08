from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import selectinload

from hmanga.database import AppMeta, Database, Tag, TagGroup, Work, WorkTag
from hmanga.text import natural_key, normalize_text, search_terms

AUTHOR_GROUP_NAME = "作者"
AUTHOR_GROUP_NORMALIZED = normalize_text(AUTHOR_GROUP_NAME)


@dataclass(frozen=True, slots=True)
class CatalogQuery:
    text: str = ""
    # None means that the caller did not request a type filter. An explicitly
    # empty tuple means that the user deselected both system type tags.
    kinds: tuple[str, ...] | None = None
    tag_ids: tuple[int, ...] = ()
    tag_mode: str = "any"
    rating_mode: str = "any"
    rating: int = 0
    sort_by: str = "added"
    descending: bool = True
    page: int = 1
    page_size: int = 50


@dataclass(frozen=True, slots=True)
class CatalogPage:
    items: list[Work]
    total: int
    page: int
    pages: int


class CatalogService:
    def __init__(self, database: Database) -> None:
        self.database = database
        with self.database.session() as session:
            if not session.scalar(
                select(TagGroup).where(TagGroup.normalized_name == AUTHOR_GROUP_NORMALIZED)
            ):
                session.add(
                    TagGroup(
                        name=AUTHOR_GROUP_NAME,
                        normalized_name=AUTHOR_GROUP_NORMALIZED,
                    )
                )

    @staticmethod
    def is_author_group(group: TagGroup | None) -> bool:
        return group is not None and group.normalized_name == AUTHOR_GROUP_NORMALIZED

    @classmethod
    def is_author_tag(cls, tag: Tag) -> bool:
        return cls.is_author_group(tag.group)

    def setting(self, key: str, default: str) -> str:
        with self.database.session() as session:
            value = session.get(AppMeta, key)
            return value.value if value else default

    def set_setting(self, key: str, value: str) -> None:
        with self.database.session() as session:
            setting = session.get(AppMeta, key)
            if setting is None:
                session.add(AppMeta(key=key, value=value))
            else:
                setting.value = value
                setting.updated_at = datetime.now(UTC)

    def query(self, query: CatalogQuery) -> CatalogPage:
        conditions = []
        terms = search_terms(query.text)
        if terms:
            conditions.append(
                or_(
                    *[
                        or_(
                            Work.normalized_file_name.contains(term),
                            Work.normalized_title.contains(term),
                        )
                        for term in terms
                    ]
                )
            )
        if query.kinds == ():
            conditions.append(Work.id.is_(None))
        elif query.kinds is not None and len(query.kinds) == 1:
            conditions.append(Work.kind == query.kinds[0])
        if query.rating_mode == "exact":
            conditions.append(Work.rating == query.rating)
        elif query.rating_mode == "at_least":
            conditions.append(Work.rating >= query.rating)
        elif query.rating_mode == "unrated":
            conditions.append(Work.rating == 0)
        if query.tag_ids:
            if query.tag_mode == "all":
                conditions.extend(Work.tags.any(Tag.id == tag_id) for tag_id in query.tag_ids)
            else:
                conditions.append(Work.tags.any(Tag.id.in_(query.tag_ids)))

        base = select(Work).where(and_(*conditions)) if conditions else select(Work)
        count_statement = select(func.count()).select_from(base.subquery())
        order_column = {
            "file_name": Work.normalized_file_name,
            "title": Work.normalized_title,
            "rating": Work.rating,
        }.get(query.sort_by, Work.added_at)
        order = order_column.desc() if query.descending else order_column.asc()
        with self.database.session() as session:
            total = session.scalar(count_statement) or 0
            pages = max(1, (total + query.page_size - 1) // query.page_size)
            page = min(max(1, query.page), pages)
            statement = (
                base.options(selectinload(Work.tags).selectinload(Tag.group))
                .order_by(order, Work.id.desc() if query.descending else Work.id.asc())
                .offset((page - 1) * query.page_size)
                .limit(query.page_size)
            )
            items = list(session.scalars(statement))
        return CatalogPage(items=items, total=total, page=page, pages=pages)

    def get_work(self, work_id: int) -> Work | None:
        with self.database.session() as session:
            return session.scalar(
                select(Work)
                .where(Work.id == work_id)
                .options(selectinload(Work.tags).selectinload(Tag.group))
            )

    def find_by_file_names(self, names: list[str]) -> list[Work]:
        if not names:
            return []
        with self.database.session() as session:
            return list(
                session.scalars(
                    select(Work)
                    .where(Work.file_name.in_(names))
                    .options(selectinload(Work.tags).selectinload(Tag.group))
                )
            )

    def update_work(
        self, work_id: int, *, title: str, rating: int, tag_ids: list[int], cover_member: str | None
    ) -> Work:
        if rating not in range(4):
            raise ValueError("星级必须是 0 到 3")
        with self.database.session() as session:
            work = session.get(Work, work_id)
            if work is None:
                raise ValueError("作品不存在")
            tags = list(session.scalars(select(Tag).where(Tag.id.in_(set(tag_ids)))))
            if len(tags) != len(set(tag_ids)):
                raise ValueError("包含不存在的 Tag")
            work.title = title.strip() or None
            work.normalized_title = normalize_text(work.title)
            work.rating = rating
            work.cover_member = cover_member
            work.tags = tags
            work.updated_at = datetime.now(UTC)
        updated = self.get_work(work_id)
        assert updated is not None
        return updated

    def list_groups(self) -> list[TagGroup]:
        with self.database.session() as session:
            groups = list(session.scalars(select(TagGroup).options(selectinload(TagGroup.tags))))
        return sorted(
            groups,
            key=lambda item: (
                0 if self.is_author_group(item) else 1,
                natural_key(item.name),
            ),
        )

    def list_tags(self, search: str = "") -> list[Tag]:
        term = normalize_text(search)
        with self.database.session() as session:
            tags = list(
                session.scalars(
                    select(Tag).options(selectinload(Tag.group), selectinload(Tag.works))
                )
            )
        if term:
            tags = [
                tag
                for tag in tags
                if term in tag.normalized_name
                or (tag.group is not None and term in tag.group.normalized_name)
            ]
        return sorted(
            tags,
            key=lambda item: (
                0 if self.is_author_tag(item) else 1,
                natural_key(self.tag_display_name(item, tags)),
            ),
        )

    @staticmethod
    def tag_display_name(tag: Tag, all_tags: list[Tag]) -> str:
        if tag.group and tag.group.normalized_name == AUTHOR_GROUP_NORMALIZED:
            return tag.name
        duplicate = sum(item.normalized_name == tag.normalized_name for item in all_tags) > 1
        if not duplicate:
            return tag.name
        return f"{tag.group.name if tag.group else '未分组'}：{tag.name}"

    def create_group(self, name: str) -> TagGroup:
        name = self._validate_tag_name(name, "分组")
        normalized = normalize_text(name)
        with self.database.session() as session:
            if session.scalar(select(TagGroup).where(TagGroup.normalized_name == normalized)):
                raise ValueError("分组名称已存在")
            group = TagGroup(name=name, normalized_name=normalized)
            session.add(group)
            session.flush()
            group_id = group.id
        with self.database.session() as session:
            return session.get(TagGroup, group_id)  # type: ignore[return-value]

    def create_tag(self, name: str, group_id: int | None = None) -> Tag:
        with self.database.session() as session:
            group = session.get(TagGroup, group_id) if group_id is not None else None
            if group_id is not None and group is None:
                raise ValueError("分组不存在")
            name = self._validate_tag_name(
                name,
                "Tag",
                unlimited=self.is_author_group(group),
            )
            normalized = normalize_text(name)
            group_key = group_id or 0
            duplicate = session.scalar(
                select(Tag).where(
                    Tag.group_key == group_key,
                    Tag.normalized_name == normalized,
                )
            )
            if duplicate:
                raise ValueError("该分组中已有同名 Tag")
            tag = Tag(
                name=name,
                normalized_name=normalized,
                group_id=group_id,
                group_key=group_key,
            )
            session.add(tag)
            session.flush()
            tag_id = tag.id
        with self.database.session() as session:
            return session.get(Tag, tag_id)  # type: ignore[return-value]

    def delete_tag(self, tag_id: int) -> int:
        with self.database.session() as session:
            count = (
                session.scalar(
                    select(func.count()).select_from(WorkTag).where(WorkTag.tag_id == tag_id)
                )
                or 0
            )
            if session.get(Tag, tag_id) is None:
                raise ValueError("Tag 不存在")
            session.execute(delete(Tag).where(Tag.id == tag_id))
        return count

    def rename_group(self, group_id: int, name: str) -> None:
        with self.database.session() as session:
            group = session.get(TagGroup, group_id)
            if group is None:
                raise ValueError("分组不存在")
            if self.is_author_group(group):
                raise ValueError("系统分组“作者”不能改名")
            name = self._validate_tag_name(name, "分组")
            normalized = normalize_text(name)
            duplicate = session.scalar(
                select(TagGroup).where(
                    TagGroup.normalized_name == normalized,
                    TagGroup.id != group_id,
                )
            )
            if duplicate:
                raise ValueError("分组名称已存在")
            group.name = name
            group.normalized_name = normalized

    def rename_tag(self, tag_id: int, name: str) -> None:
        with self.database.session() as session:
            tag = session.get(Tag, tag_id)
            if tag is None:
                raise ValueError("Tag 不存在")
            name = self._validate_tag_name(
                name,
                "Tag",
                unlimited=self.is_author_tag(tag),
            )
            normalized = normalize_text(name)
            duplicate = session.scalar(
                select(Tag).where(
                    Tag.group_key == tag.group_key,
                    Tag.normalized_name == normalized,
                    Tag.id != tag_id,
                )
            )
            if duplicate:
                raise ValueError("该分组中已有同名 Tag")
            tag.name = name
            tag.normalized_name = normalized

    @staticmethod
    def _validate_tag_name(name: str, kind: str, *, unlimited: bool = False) -> str:
        value = name.strip()
        if not value:
            raise ValueError(f"{kind} 名称不能为空")
        if not unlimited and len(value) > 5:
            raise ValueError(f"{kind} 名称最多 5 个字符")
        return value

    def move_tag(self, tag_id: int, group_id: int | None) -> None:
        with self.database.session() as session:
            tag = session.get(Tag, tag_id)
            if tag is None:
                raise ValueError("Tag 不存在")
            group = session.get(TagGroup, group_id) if group_id is not None else None
            if group_id is not None and group is None:
                raise ValueError("分组不存在")
            if not self.is_author_group(group) and len(tag.name) > 5:
                raise ValueError("作者 Tag 超过 5 个字符，不能移出作者分组")
            group_key = group_id or 0
            duplicate = session.scalar(
                select(Tag).where(
                    Tag.group_key == group_key,
                    Tag.normalized_name == tag.normalized_name,
                    Tag.id != tag_id,
                )
            )
            if duplicate:
                raise ValueError("目标分组中已有同名 Tag")
            tag.group_id = group_id
            tag.group_key = group_key

    def group_impact(self, group_id: int) -> tuple[int, int]:
        with self.database.session() as session:
            tags = select(Tag.id).where(Tag.group_id == group_id)
            comics = (
                session.scalar(
                    select(func.count(func.distinct(Work.id)))
                    .join(WorkTag, WorkTag.work_id == Work.id)
                    .where(WorkTag.tag_id.in_(tags), Work.kind == "comic")
                )
                or 0
            )
            illustrations = (
                session.scalar(
                    select(func.count(func.distinct(Work.id)))
                    .join(WorkTag, WorkTag.work_id == Work.id)
                    .where(WorkTag.tag_id.in_(tags), Work.kind == "illustration")
                )
                or 0
            )
        return comics, illustrations

    def delete_group(self, group_id: int, delete_tags: bool) -> tuple[int, int]:
        impact = self.group_impact(group_id)
        with self.database.session() as session:
            group = session.get(TagGroup, group_id)
            if group is None:
                raise ValueError("分组不存在")
            if self.is_author_group(group):
                raise ValueError("系统分组“作者”不能删除")
            tags = list(session.scalars(select(Tag).where(Tag.group_id == group_id)))
            if delete_tags:
                for tag in tags:
                    session.delete(tag)
            else:
                ungrouped_names = {
                    value
                    for value in session.scalars(
                        select(Tag.normalized_name).where(Tag.group_id.is_(None))
                    )
                }
                conflicts = [tag.name for tag in tags if tag.normalized_name in ungrouped_names]
                if conflicts:
                    raise ValueError("未分组中已有同名 Tag：" + "、".join(conflicts))
                for tag in tags:
                    tag.group_id = None
                    tag.group_key = 0
            session.delete(group)
        return impact

    def reset_custom_metadata(self) -> None:
        """Remove user Tags/groups and titles without touching media files."""
        with self.database.session() as session:
            session.execute(delete(WorkTag))
            session.execute(delete(Tag))
            session.execute(
                delete(TagGroup).where(
                    TagGroup.normalized_name != AUTHOR_GROUP_NORMALIZED
                )
            )
            session.execute(update(Work).values(title=None, normalized_title=""))
