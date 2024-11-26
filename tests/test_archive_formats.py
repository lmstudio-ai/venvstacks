"""Test archive creation."""

import pytest

from venvstacks.pack_venv import ArchiveFormat, DEFAULT_ARCHIVE_FORMAT


@pytest.mark.parametrize("archive_format", ArchiveFormat.__members__.values())
def test_archive_formats(archive_format: ArchiveFormat) -> None:
    # Every defined format can be resolved from the corresponding string value
    assert ArchiveFormat.get_archive_format(str(archive_format)) is archive_format
    # Every defined archive format must resolve to a defined compression algorithm
    assert archive_format.get_compression() is not None
    # The archive format is used as the extension
    assert (
        archive_format.get_archive_path("example").name == f"example.{archive_format}"
    )


def test_default_archive_format() -> None:
    assert ArchiveFormat.get_archive_format(None) is DEFAULT_ARCHIVE_FORMAT


# TODO: Actually test CompressionAlgorithms.make_archive for each archive format
