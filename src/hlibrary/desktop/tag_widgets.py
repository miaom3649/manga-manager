from html import escape

TAG_PREFIX_COLOR = "#b69de0"
TAG_CHIP_PREFIX_COLOR = "#c2bec7"
AUTHOR_TAG_COLOR = "#d6a928"


def tag_sort_category(display_name: str, font_metrics, *, author: bool = False) -> int:
    """Order author Tags, prefixed Tags, plain long Tags, then short Tags."""
    if author:
        return 0
    if "：" in display_name:
        return 1
    return 2 if font_metrics.horizontalAdvance(display_name) + 26 > 78 else 3


def is_long_tag_category(category: int) -> bool:
    return category < 3


def tag_chip_text(display_name: str) -> str:
    """Return rich text that distinguishes an optional group prefix."""
    prefix, separator, name = display_name.partition("：")
    if not separator:
        return escape(display_name)
    return (
        f'<span style="color:{TAG_CHIP_PREFIX_COLOR}">{escape(prefix + separator)}</span>'
        f'<span style="color:white">{escape(name)}</span>'
    )
