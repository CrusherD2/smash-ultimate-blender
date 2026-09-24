"""Parse CHANGELOG.md into per-version patch notes for the updater.

Pure Python (no bpy) so it can be unit tested outside Blender. Expected format:

    ## 4.8.0 - 2026-10-01
    - A user-facing note
    - Another note

Headings may also be written as `## [4.8.0]` or `## v4.8`. Headings that are not
versions (e.g. `## Unreleased`) and text before the first version are ignored.
"""
from dataclasses import dataclass, field
import re

_HEADING_RE = re.compile(r'^##\s+\[?v?(\d+(?:\.\d+){1,2})\]?\s*(?:[-–—]\s*(.*?))?\s*$')
_VERSION_RE = re.compile(r'^\s*v?(\d+(?:\.\d+){0,2})\s*$')
_BULLET_RE = re.compile(r'^\s*[-*•]\s+')


@dataclass
class ChangelogSection:
    version: tuple
    date: str = ''
    notes: list = field(default_factory=list)


def parse_version(text):
    """'4.7.1' / 'v4.7' -> (4, 7, 1) / (4, 7, 0); None when it is not a version."""
    match = _VERSION_RE.match(text or '')
    if not match:
        return None
    parts = [int(part) for part in match.group(1).split('.')]
    return tuple(parts + [0] * (3 - len(parts)))


def format_version(version):
    return '.'.join(str(part) for part in version) if version else '?'


def parse_changelog(text):
    """Return version sections, newest first."""
    sections = []
    current = None
    for raw_line in (text or '').splitlines():
        # Headings must start the line; indented ones are Markdown code examples.
        heading = _HEADING_RE.match(raw_line.rstrip())
        if heading:
            current = ChangelogSection(parse_version(heading.group(1)), (heading.group(2) or '').strip())
            sections.append(current)
            continue
        if raw_line.startswith('#'):
            # Any other heading (e.g. "## Unreleased") ends the current section.
            current = None
            continue
        if current is None or not raw_line.strip():
            continue
        if _BULLET_RE.match(raw_line):
            current.notes.append(_BULLET_RE.sub('', raw_line).strip())
        elif current.notes and raw_line[:1].isspace():
            # Indented continuation of the previous bullet.
            current.notes[-1] += ' ' + raw_line.strip()
        else:
            current.notes.append(raw_line.strip())
    sections.sort(key=lambda section: section.version, reverse=True)
    return sections


def sections_between(sections, installed, remote):
    """Sections newer than `installed` and no newer than `remote`.

    With no known installed version only the remote version's notes are shown,
    so a user never gets the entire project history in one popup.
    """
    if installed is None:
        return [section for section in sections if remote is not None and section.version == remote]
    return [
        section for section in sections
        if section.version > installed and (remote is None or section.version <= remote)
    ]


def section_for(sections, version):
    return next((section for section in sections if section.version == version), None)
