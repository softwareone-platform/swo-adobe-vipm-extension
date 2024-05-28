from dataclasses import dataclass


@dataclass
class ItemGroups:
    upsizing_in_win: list
    upsizing_out_win_or_migrated: list
    downsizing_in_win: list
    downsizing_out_win_or_migrated: list
