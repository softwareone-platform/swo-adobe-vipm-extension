from dataclasses import dataclass


@dataclass
class ItemGroups:
    upsizing: list
    downsizing_in_win: list
    downsizing_out_win: list
