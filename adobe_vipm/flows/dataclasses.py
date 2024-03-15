from dataclasses import dataclass


@dataclass
class ItemGroups:
    upsizing_in_win: list
    upsizing_out_win: list
    downsizing_in_win: list
    downsizing_out_win: list
