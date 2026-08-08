from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hmanga.catalog import CatalogQuery, CatalogService
from hmanga.database import Database, Work
from hmanga.text import normalize_text


@pytest.fixture
def database(tmp_path) -> Database:
    value = Database(tmp_path / "catalog.db")
    value.initialize("test")
    return value


def add_work(database: Database, name: str, title: str, rating: int = 0) -> int:
    with database.session() as session:
        work = Work(
            kind="comic",
            relative_path=name,
            file_name=name,
            normalized_file_name=normalize_text(name),
            title=title,
            normalized_title=normalize_text(title),
            rating=rating,
            file_size=1,
            modified_ns=1,
            status="ready",
            added_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(work)
        session.flush()
        return work.id


def test_unicode_search_tags_and_rating(database: Database) -> None:
    catalog = CatalogService(database)
    first = add_work(database, "４５９８０８.zip", "青山作品", 3)
    add_work(database, "123.zip", "别的作品", 1)
    group = catalog.list_groups()[0]
    tag = catalog.create_tag("青山", group.id)
    catalog.update_work(first, title="青山作品", rating=3, tag_ids=[tag.id], cover_member=None)

    page = catalog.query(
        CatalogQuery(text="459", tag_ids=(tag.id,), rating_mode="at_least", rating=2)
    )

    assert page.total == 1
    assert page.items[0].id == first
    assert page.items[0].tags[0].name == "青山"


def test_explicitly_deselecting_both_system_tags_returns_no_works(database: Database) -> None:
    catalog = CatalogService(database)
    add_work(database, "123.zip", "作品")

    assert catalog.query(CatalogQuery()).total == 1
    assert catalog.query(CatalogQuery(kinds=())).total == 0


def test_tag_duplicate_display_uses_group_prefix(database: Database) -> None:
    catalog = CatalogService(database)
    author = catalog.create_group("原作")
    category = catalog.create_group("类别")
    catalog.create_tag("青山", author.id)
    catalog.create_tag("青山", category.id)

    tags = catalog.list_tags()

    assert [catalog.tag_display_name(tag, tags) for tag in tags] == ["原作：青山", "类别：青山"]


def test_tag_and_group_names_are_limited_to_five_characters(database: Database) -> None:
    catalog = CatalogService(database)
    group = catalog.create_group("一二三四五")
    tag = catalog.create_tag("abcde", group.id)

    with pytest.raises(ValueError, match="最多 5 个字符"):
        catalog.create_group("一二三四五六")
    with pytest.raises(ValueError, match="最多 5 个字符"):
        catalog.create_tag("abcdef")
    with pytest.raises(ValueError, match="最多 5 个字符"):
        catalog.rename_group(group.id, "一二三四五六")
    with pytest.raises(ValueError, match="最多 5 个字符"):
        catalog.rename_tag(tag.id, "abcdef")


def test_move_and_delete_group_rules(database: Database) -> None:
    catalog = CatalogService(database)
    group = catalog.create_group("系列")
    tag = catalog.create_tag("青山", group.id)
    catalog.rename_tag(tag.id, "青山刚昌")
    catalog.move_tag(tag.id, None)
    assert catalog.list_tags()[0].group is None
    catalog.move_tag(tag.id, group.id)
    catalog.delete_group(group.id, delete_tags=False)
    assert catalog.list_tags()[0].group is None

    second = catalog.create_group("类别")
    second_tag = catalog.create_tag("恋爱", second.id)
    catalog.delete_group(second.id, delete_tags=True)
    assert all(item.id != second_tag.id for item in catalog.list_tags())


def test_author_system_group_rules(database: Database) -> None:
    catalog = CatalogService(database)
    author = catalog.list_groups()[0]
    assert author.name == "作者"
    tag = catalog.create_tag("这是一个很长的作者名称", author.id)
    tags = catalog.list_tags()

    assert catalog.tag_display_name(tags[0], tags) == tag.name
    with pytest.raises(ValueError, match="不能改名"):
        catalog.rename_group(author.id, "原作")
    with pytest.raises(ValueError, match="不能删除"):
        catalog.delete_group(author.id, delete_tags=False)
    with pytest.raises(ValueError, match="不能移出"):
        catalog.move_tag(tag.id, None)


def test_reset_custom_metadata_keeps_media_and_author_group(database: Database) -> None:
    catalog = CatalogService(database)
    work_id = add_work(database, "123.zip", "自定义标题")
    custom_group = catalog.create_group("类别")
    tag = catalog.create_tag("恋爱", custom_group.id)
    catalog.update_work(
        work_id,
        title="修改标题",
        rating=3,
        tag_ids=[tag.id],
        cover_member="002.webp",
    )

    catalog.reset_custom_metadata()

    work = catalog.get_work(work_id)
    assert work is not None
    assert work.title is None
    assert work.tags == []
    assert work.rating == 3
    assert work.cover_member == "002.webp"
    assert catalog.list_tags() == []
    assert [group.name for group in catalog.list_groups()] == ["作者"]
