from html import escape

AUTHOR_TAG_COLOR = "#b89a58"


def tag_sort_category(display_name: str, font_metrics, *, author: bool = False) -> int:
    """Order author Tags, plain long Tags, then short Tags."""
    if author:
        return 0
    return 2 if font_metrics.horizontalAdvance(display_name) + 26 > 78 else 3


def is_long_tag_category(category: int) -> bool:
    return category < 3


def tag_chip_text(display_name: str) -> str:
    return escape(display_name)
