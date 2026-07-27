"""Unit tests for reusable response primitives."""

import pytest
from platform_api.models.common import PaginationMeta, PaginationParams
from pydantic import ValidationError


def test_pagination_meta_computes_has_more() -> None:
    """Offset pagination exposes a stable continuation signal."""
    params = PaginationParams(offset=20, limit=20)

    assert PaginationMeta.from_params(params, total=41).has_more is True
    assert PaginationMeta.from_params(params, total=40).has_more is False


def test_pagination_rejects_unbounded_page_size() -> None:
    """Callers cannot request more than the global maximum page size."""
    with pytest.raises(ValidationError):
        PaginationParams(limit=101)
