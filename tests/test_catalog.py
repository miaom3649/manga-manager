from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hmanga.catalog import CatalogQuery, CatalogService
from hmanga.database import Database, Tag, TagGroup, Work, WorkTag
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
    author, category = catalog.list_groups()
    catalog.create_tag("青山", author.id)
    catalog.create_tag("青山", category.id)

    tags = catalog.list_tags()

    assert [catalog.tag_display_name(tag, tags) for tag in tags] == ["青山", "青山"]


def test_same_tag_name_can_exist_in_author_and_category(database: Database) -> None:
    catalog = CatalogService(database)
    author, category = catalog.list_groups()

    category_tag = catalog.create_tag("a", category.id)
    author_tag = catalog.create_tag("a", author.id)

    assert category_tag.id != author_tag.id
    assert [tag.name for tag in catalog.list_tags()] == ["a", "a"]


def test_category_tag_names_are_limited_to_five_characters(database: Database) -> None:
    catalog = CatalogService(database)
    tag = catalog.create_tag("abcde")

    with pytest.raises(ValueError, match="只能使用系统分组"):
        catalog.create_group("新分组")
    with pytest.raises(ValueError, match="最多 5 个字符"):
        catalog.create_tag("abcdef")
    with pytest.raises(ValueError, match="最多 5 个字符"):
        catalog.rename_tag(tag.id, "abcdef")


def test_only_fixed_groups_are_available(database: Database) -> None:
    catalog = CatalogService(database)
    author, category = catalog.list_groups()
    tag = catalog.create_tag("恋爱")
    assert tag.group_id == category.id
    catalog.move_tag(tag.id, author.id)
    assert catalog.list_tags()[0].group_id == author.id
    catalog.move_tag(tag.id, None)
    assert catalog.list_tags()[0].group_id == category.id
    for group in (author, category):
        with pytest.raises(ValueError, match="不能改名"):
            catalog.rename_group(group.id, "新名")
        with pytest.raises(ValueError, match="不能删除"):
            catalog.delete_group(group.id, delete_tags=False)


def test_edit_tag_updates_name_and_group_atomically(database: Database) -> None:
    catalog = CatalogService(database)
    author, category = catalog.list_groups()
    tag = catalog.create_tag("恋爱", category.id)

    catalog.edit_tag(tag.id, "很长的作者名称", author.id)

    updated = catalog.list_tags()[0]
    assert updated.name == "很长的作者名称"
    assert updated.group_id == author.id
    with pytest.raises(ValueError, match="最多 5 个字符"):
        catalog.edit_tag(tag.id, updated.name, category.id)
    unchanged = catalog.list_tags()[0]
    assert unchanged.name == "很长的作者名称"
    assert unchanged.group_id == author.id


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
    tag = catalog.create_tag("恋爱")
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
    assert [group.name for group in catalog.list_groups()] == ["作者", "类别"]


def test_text_search_unions_title_tag_and_group_matches(database: Database) -> None:
    catalog = CatalogService(database)
    author, category = catalog.list_groups()
    title_match = add_work(database, "1.zip", "作者之夜")
    tag_match = add_work(database, "2.zip", "其他")
    group_match = add_work(database, "3.zip", "另一部")
    unrelated = add_work(database, "4.zip", "无关")
    category_named_author = catalog.create_tag("作者", category.id)
    actual_author = catalog.create_tag("青山刚昌", author.id)
    catalog.update_work(
        tag_match,
        title="其他",
        rating=0,
        tag_ids=[category_named_author.id],
        cover_member=None,
    )
    catalog.update_work(
        group_match,
        title="另一部",
        rating=0,
        tag_ids=[actual_author.id],
        cover_member=None,
    )

    result = catalog.query(CatalogQuery(text="作者"))

    assert {work.id for work in result.items} == {title_match, tag_match, group_match}
    assert unrelated not in {work.id for work in result.items}


def test_legacy_groups_and_ungrouped_tags_merge_into_category(database: Database) -> None:
    first = add_work(database, "1.zip", "一")
    second = add_work(database, "2.zip", "二")
    with database.session() as session:
        legacy_group = TagGroup(name="旧分组", normalized_name=normalize_text("旧分组"))
        session.add(legacy_group)
        session.flush()
        grouped = Tag(
            name="恋爱",
            normalized_name=normalize_text("恋爱"),
            group_id=legacy_group.id,
            group_key=legacy_group.id,
        )
        ungrouped = Tag(
            name="恋爱",
            normalized_name=normalize_text("恋爱"),
            group_id=None,
            group_key=0,
        )
        session.add_all([grouped, ungrouped])
        session.flush()
        session.add_all(
            [
                WorkTag(work_id=first, tag_id=grouped.id),
                WorkTag(work_id=second, tag_id=ungrouped.id),
            ]
        )

    catalog = CatalogService(database)

    tags = catalog.list_tags()
    assert len(tags) == 1
    assert tags[0].group is not None and tags[0].group.name == "类别"
    assert {work.id for work in tags[0].works} == {first, second}
    assert [group.name for group in catalog.list_groups()] == ["作者", "类别"]


def test_catalog_revision_changes_after_shared_metadata_edits(database: Database) -> None:
    catalog = CatalogService(database)
    work_id = add_work(database, "123.zip", "作品")
    initial = catalog.revision
    tag = catalog.create_tag("测试")
    assert catalog.revision > initial
    after_tag = catalog.revision

    catalog.update_work(
        work_id,
        title="新标题",
        rating=1,
        tag_ids=[tag.id],
        cover_member=None,
    )

    assert catalog.revision > after_tag


def test_catalog_revision_can_publish_library_scan_changes(database: Database) -> None:
    catalog = CatalogService(database)
    revision = catalog.revision

    catalog.notify_library_changed()

    assert catalog.revision == revision + 1


def test_delete_work_removes_its_database_record(database: Database) -> None:
    catalog = CatalogService(database)
    work_id = add_work(database, "123.zip", "作品")
    tag = catalog.create_tag("测试")
    catalog.update_work(
        work_id,
        title="作品",
        rating=1,
        tag_ids=[tag.id],
        cover_member=None,
    )
    revision = catalog.revision

    catalog.delete_work(work_id)

    assert catalog.get_work(work_id) is None
    assert catalog.revision > revision
