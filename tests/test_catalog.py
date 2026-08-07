from __future__ import annotations

from datetime import UTC, datetime

import pytest

from hlibrary.catalog import CatalogQuery, CatalogService
from hlibrary.database import Database, Work
from hlibrary.text import normalize_text


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
    group = catalog.create_group("作者")
    tag = catalog.create_tag("青山", group.id)
    catalog.update_work(first, title="青山作品", rating=3, tag_ids=[tag.id], cover_member=None)

    page = catalog.query(
        CatalogQuery(text="459", tag_ids=(tag.id,), rating_mode="at_least", rating=2)
    )

    assert page.total == 1
    assert page.items[0].id == first
    assert page.items[0].tags[0].name == "青山"


def test_tag_duplicate_display_uses_group_prefix(database: Database) -> None:
    catalog = CatalogService(database)
    author = catalog.create_group("作者")
    category = catalog.create_group("类别")
    catalog.create_tag("青山", author.id)
    catalog.create_tag("青山", category.id)

    tags = catalog.list_tags()

    assert [catalog.tag_display_name(tag, tags) for tag in tags] == ["作者：青山", "类别：青山"]


def test_move_and_delete_group_rules(database: Database) -> None:
    catalog = CatalogService(database)
    group = catalog.create_group("作者")
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
