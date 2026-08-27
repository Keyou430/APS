from __future__ import annotations

import pytest

from scripts.benchmark_rag_capacity import parse_targets


def test_parse_targets_requires_unique_increasing_positive_values() -> None:
    assert parse_targets("100000,1000000") == [100000, 1000000]
    for invalid in ("0", "100,10", "100,100"):
        with pytest.raises(ValueError, match="capacity targets"):
            parse_targets(invalid)
