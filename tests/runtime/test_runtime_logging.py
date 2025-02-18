from swo.mpt.extensions.runtime.logging import ReprHighlighter


def test_repr_highlighter(
    mock_logging_account_prefixes,
    mock_logging_catalog_prefixes,
    mock_logging_commerce_prefixes,
    mock_logging_aux_prefixes,
    mock_logging_all_prefixes,
    mock_highlights,
):
    repr_highlighter = ReprHighlighter()
    assert repr_highlighter.accounts_prefixes == mock_logging_account_prefixes
    assert repr_highlighter.catalog_prefixes == mock_logging_catalog_prefixes
    assert repr_highlighter.commerce_prefixes == mock_logging_commerce_prefixes
    assert repr_highlighter.aux_prefixes == mock_logging_aux_prefixes
    assert repr_highlighter.all_prefixes == mock_logging_all_prefixes
    assert repr_highlighter.highlights == mock_highlights
