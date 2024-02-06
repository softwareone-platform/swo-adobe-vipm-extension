from rich.highlighter import ReprHighlighter as _ReprHighlighter
from rich.logging import RichHandler as _RichHandler


class ReprHighlighter(_ReprHighlighter):
    accounts_prefixes = ("ACC", "BUY", "LCE", "MOD", "SEL", "USR", "AUSR", "UGR")
    catalog_prefixes = (
        "PRD",
        "ITM",
        "IGR",
        "PGR",
        "MED",
        "DOC",
        "TCS",
        "TPL",
        "WHO",
        "PRC",
        "LST",
        "AUT",
        "UNT",
    )
    commerce_prefixes = ("AGR", "ORD", "SUB", "REQ")
    aux_prefixes = ("FIL", "MSG")
    all_prefixes = (*accounts_prefixes, *catalog_prefixes, *commerce_prefixes, *aux_prefixes)
    highlights = _ReprHighlighter.highlights + [
        rf"(?P<mpt_id>(?:{'|'.join(all_prefixes)})(?:-\d{{4}})*)"
    ]


class RichHandler(_RichHandler):
    HIGHLIGHTER_CLASS = ReprHighlighter
