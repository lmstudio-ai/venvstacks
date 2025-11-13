#!/usr/bin/env python
"""Minimalist script to create a local package repository with metadata support."""

# Repository format: https://packaging.python.org/en/latest/specifications/simple-repository-api/#html-serialization

# This script is designed to take a directory tree using the basic format in
# https://packaging.python.org/en/latest/guides/hosting-your-own-index/#manual-repository
# and enhance it by adding index.html files that include artifact hash metadata
# While it doesn't currently extract wheel metadata, it could be enhanced to do so

# This script is intended to help replace flat local directories indexes with a
# local index server without adding any new dependencies outside the Python
# standard library. If additional dependencies are acceptable, consider
# https://pypi.org/project/dumb-pypi/ as a more capable alternative.

import hashlib
import sys

from pathlib import Path
from typing import Iterable, Sequence, TypedDict

_INDEX_HEADER_FMT = """
<!DOCTYPE html>
<html lang="en">
  <head>
    <title>Links for {project}</title>
  </head>
  <body>
    <h1>Links for {project}</h1>
"""

_ARTIFACT_LINK_FMT = """
<a href="./{name}#sha256={sha256}" >{name}</a><br />
"""

_INDEX_FOOTER = """
</body>
</html>
"""

class ArtifactLinkInfo(TypedDict):
    """Information to be included in a project artifact link."""
    name: str
    sha256: str


def render_project_detail_index(project: str, artifacts: Iterable[ArtifactLinkInfo]) -> str:
    """Generate simple repository API project detail index.html files."""
    rendered_header = _INDEX_HEADER_FMT.format(project=project)
    rendered_links = "\n".join(
        _ARTIFACT_LINK_FMT.format_map(artifact) for artifact in artifacts
    )
    return f"{rendered_header}{rendered_links}{_INDEX_FOOTER}"

def get_project_artifact_info(project_details_path: Path) -> Sequence[ArtifactLinkInfo]:
    """Read project artifact details from directory contents."""
    artifact_details: list[ArtifactLinkInfo] = []
    for dir_entry in project_details_path.iterdir():
        # Add index links only for regular (non-symlinked) files
        # (follow_symlinks=False is avoided for Python < 3.13 compatibility)
        if dir_entry.is_file() and not dir_entry.is_symlink():
            continue
        sha256_hash = hashlib.sha256(dir_entry.read_bytes())
        artifact_details.append({
            "name": dir_entry.name,
            "sha256": sha256_hash.hexdigest(),
        })
    return artifact_details

def write_project_detail_file(project_details_path: Path) -> None:
    """Generate simple repository API project detail index.html files."""
    project = project_details_path.name
    artifact_details = get_project_artifact_info(project_details_path)
    index_contents = render_project_detail_index(project, artifact_details)
    index_path = project_details_path / "index.html"
    index_path.write_text(index_contents, newline="\n", encoding="utf-8")

def write_project_detail_files(repository_path: Path) -> None:
    """Generate simple repository API project detail index.html files."""
    for dir_entry in repository_path.iterdir():
        if dir_entry.is_dir():
            write_project_detail_file(dir_entry)

def main() -> None:
    """Generate simple repository API project detail index.html files."""
    write_project_detail_files(Path(sys.argv[1]))

if __name__ == "__main__":
    main()
