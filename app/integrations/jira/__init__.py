"""Jira Data Center integration primitives."""

from .pagination import JiraPaginationError, collect_offset_pages

__all__ = ["JiraPaginationError", "collect_offset_pages"]
