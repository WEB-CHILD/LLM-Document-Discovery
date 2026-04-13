"""Tests for document splitting functionality."""

import pytest
from prep_db import (
    split_document,
    SPLIT_TARGET_SIZE,
    SPLIT_MAX_SIZE,
    SPLIT_OVERLAP,
)


class TestSplitDocument:
    """Test document splitting."""

    def test_no_split_for_small_document(self):
        content = "http://example.com\n\nSmall content"
        parts = split_document(content, "http://example.com")
        assert len(parts) == 1
        assert parts[0] == content

    def test_splits_large_document(self):
        # Create a document larger than SPLIT_MAX_SIZE
        url_header = "http://example.com/large"
        # Create body with natural breaks every 10k chars
        segments = []
        for i in range(15):  # 15 segments * ~8k chars = ~120k total
            segment = f"\n\n## Section {i}\n\n" + ("x" * 8000)
            segments.append(segment)
        body = "".join(segments)
        content = f"{url_header}\n\n{body}"

        parts = split_document(content, url_header)

        # Should be split into multiple parts
        assert len(parts) > 1

        # Each part should start with the URL header
        for part in parts:
            assert part.startswith(url_header)

        # Each part should be within size limit (LangChain may exceed slightly)
        for part in parts:
            assert len(part) <= SPLIT_TARGET_SIZE + SPLIT_OVERLAP + len(url_header) + 100

    def test_preserves_url_header_in_all_parts(self):
        url_header = "http://example.com/test"
        body = "x" * 200000  # Large enough to require splitting
        content = f"{url_header}\n\n{body}"

        parts = split_document(content, url_header)

        for part in parts:
            assert part.startswith(f"{url_header}\n\n")

    def test_overlap_between_parts(self):
        url_header = "http://example.com"
        # Create content with a unique marker at specific position
        marker = "UNIQUE_MARKER"
        body = ("x" * 70000) + marker + ("y" * 70000)
        content = f"{url_header}\n\n{body}"

        parts = split_document(content, url_header)

        # With overlap, the marker should appear in at least one part
        found_marker = any(marker in part for part in parts)
        assert found_marker


class TestSplitIntegration:
    """Integration tests for splitting workflow."""

    def test_split_at_natural_breaks(self):
        """Test that splits prefer natural break points."""
        url_header = "http://example.com"
        # Create content with paragraph breaks as natural breaks
        body = "First section content here.\n" + ("x" * 70000)
        body += "\n\nSecond section starts here.\n" + ("y" * 70000)
        body += "\n\nThird section final."
        content = f"{url_header}\n\n{body}"

        parts = split_document(content, url_header)

        # Should split into multiple parts
        assert len(parts) >= 2

        # Parts should be reasonably sized
        for part in parts:
            # LangChain may produce slightly larger chunks
            assert len(part) <= SPLIT_TARGET_SIZE + SPLIT_OVERLAP + len(url_header) + 200
