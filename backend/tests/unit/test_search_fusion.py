"""Unit: Reciprocal Rank Fusion (домен поиска)."""
from __future__ import annotations

import pytest

from eventmind.domain.search.fusion import reciprocal_rank_fusion


def test_item_found_by_several_retrievers_wins() -> None:
    fused = reciprocal_rank_fusion([[1, 2, 3], [4, 1], [5, 1]], k=60)
    assert fused[0][0] == 1
    assert fused[0][1] == pytest.approx(1 / 61 + 1 / 62 + 1 / 62)


def test_ties_break_by_best_rank_then_first_seen() -> None:
    fused = reciprocal_rank_fusion([[1, 2], [3, 4]], k=60)
    assert [i for i, _ in fused] == [1, 3, 2, 4]


def test_duplicates_inside_one_list_count_once_and_weights_apply() -> None:
    assert reciprocal_rank_fusion([[1, 1, 2]], k=0) == [(1, 1.0), (2, pytest.approx(1 / 3))]
    weighted = reciprocal_rank_fusion([[1], [2]], k=0, weights=[1.0, 3.0])
    assert [i for i, _ in weighted] == [2, 1]
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([[1]], weights=[1.0, 2.0])


def test_empty_input() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []
