from rich.highlighter import ReprHighlighter as _ReprHighlighter
from swo.mpt.extensions.runtime.logging import ReprHighlighter, RichHandler


def test_repr_highlighter(
    mock_logging_account_prefixes,
    mock_logging_catalog_prefixes,
    mock_logging_commerce_prefixes,
    mock_logging_aux_prefixes,
):
    mock_logging_all_prefixes = (
        *mock_logging_account_prefixes,
        *mock_logging_catalog_prefixes,
        *mock_logging_commerce_prefixes,
        *mock_logging_aux_prefixes,
    )
    mock_highlights = _ReprHighlighter.highlights + [
        rf"(?P<mpt_id>(?:{'|'.join(mock_logging_all_prefixes)})(?:-\d{{4}})*)"
    ]
    repr_highlighter = ReprHighlighter()
    assert repr_highlighter.accounts_prefixes == mock_logging_account_prefixes
    assert repr_highlighter.catalog_prefixes == mock_logging_catalog_prefixes
    assert repr_highlighter.commerce_prefixes == mock_logging_commerce_prefixes
    assert repr_highlighter.aux_prefixes == mock_logging_aux_prefixes
    assert repr_highlighter.all_prefixes == mock_logging_all_prefixes
    assert repr_highlighter.highlights == mock_highlights


def test_rich_handler():
    rich_handler = RichHandler()
    assert rich_handler.HIGHLIGHTER_CLASS == ReprHighlighter
