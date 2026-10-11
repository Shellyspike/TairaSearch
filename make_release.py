#!/usr/bin/env python3
"""Build and audit a public TairaSearch ZIP from an exact file allowlist."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_MANIFEST = PROJECT_DIR / "release_manifest.toml"
DEFAULT_OUTPUT = PROJECT_DIR / "dist" / "TairaSearch.zip"
MAX_FILE_SIZE = 5 * 1024 * 1024

FORBIDDEN_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "new_sources",
    "work",
}
FORBIDDEN_NAMES = {
    "daily_five_candidates.json",
    "drive_index.csv",
    "drive_index.jsonl",
    "index_errors.log",
    "used_finds.csv",
}
FORBIDDEN_SUFFIXES = {".bak", ".db", ".pyc", ".pyo", ".sqlite", ".sqlite3"}
TEXT_SUFFIXES = {
    ".csv",
    ".ini",
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
WINDOWS_ABSOLUTE_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\")
POSIX_HOME_RE = re.compile(r"/(?:Users|home)/[^/\s]+/")


class ReleaseError(RuntimeError):
    """The public release failed a safety or consistency check."""


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _absolute(path: Path) -> Path:
    """Return a lexical absolute path without Windows realpath permission probes."""

    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _manifest_entries(manifest_path: Path) -> list[PurePosixPath]:
    try:
        raw = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReleaseError(f"Release manifest not found: {manifest_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ReleaseError(f"Invalid release manifest {manifest_path}: {exc}") from exc

    release = raw.get("release")
    if not isinstance(release, dict) or release.get("version") != 1:
        raise ReleaseError("release_manifest.toml must contain [release] version = 1")
    values = release.get("files")
    if not isinstance(values, list) or not values:
        raise ReleaseError("release.files must be a non-empty list")

    entries: list[PurePosixPath] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ReleaseError("Every release.files entry must be a non-empty string")
        if "\\" in value:
            raise ReleaseError(f"Manifest paths must use '/': {value!r}")
        relative = PurePosixPath(value)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ReleaseError(f"Unsafe manifest path: {value!r}")
        normalized = relative.as_posix()
        if normalized in seen:
            raise ReleaseError(f"Duplicate manifest path: {normalized}")
        seen.add(normalized)
        entries.append(relative)
    return entries


def _has_symlink_component(root: Path, relative: PurePosixPath) -> bool:
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _forbidden_path_reason(relative: PurePosixPath) -> str | None:
    parts = set(relative.parts)
    if parts & FORBIDDEN_PARTS:
        return "private or generated directory"
    if relative.name in FORBIDDEN_NAMES:
        return "private or generated filename"
    if relative.suffix.casefold() in FORBIDDEN_SUFFIXES:
        return "private or generated file type"
    return None


def release_entries(
    root: Path = PROJECT_DIR, manifest_path: Path | None = None
) -> list[tuple[PurePosixPath, Path]]:
    root = _absolute(root)
    manifest_path = _absolute(manifest_path or root / "release_manifest.toml")
    entries: list[tuple[PurePosixPath, Path]] = []
    for relative in _manifest_entries(manifest_path):
        reason = _forbidden_path_reason(relative)
        if reason:
            raise ReleaseError(f"Forbidden release entry ({reason}): {relative}")
        if _has_symlink_component(root, relative):
            raise ReleaseError(f"Symlinks are not allowed in releases: {relative}")
        source = root.joinpath(*relative.parts)
        if not source.exists():
            raise ReleaseError(f"Manifest file is missing: {relative}")
        if not source.is_file():
            raise ReleaseError(f"Manifest entry is not a file: {relative}")
        if source.stat().st_size > MAX_FILE_SIZE:
            raise ReleaseError(
                f"Release file is larger than {MAX_FILE_SIZE} bytes: {relative}"
            )
        entries.append((relative, source))
    return entries


def release_files(root: Path = PROJECT_DIR, manifest_path: Path | None = None) -> list[Path]:
    """Compatibility helper returning the allowlisted source files."""

    return [source for _, source in release_entries(root, manifest_path)]


def _audit_text(name: str, data: bytes) -> None:
    if PurePosixPath(name).suffix.casefold() not in TEXT_SUFFIXES:
        return
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ReleaseError(f"Public text file is not UTF-8: {name}") from exc
    if WINDOWS_ABSOLUTE_RE.search(text) or POSIX_HOME_RE.search(text):
        raise ReleaseError(f"Absolute local path found in public file: {name}")


def audit_source(
    root: Path = PROJECT_DIR, manifest_path: Path | None = None
) -> list[tuple[PurePosixPath, Path]]:
    entries = release_entries(root, manifest_path)
    for relative, source in entries:
        _audit_text(relative.as_posix(), source.read_bytes())
    return entries


def verify_release(
    path: Path,
    root: Path = PROJECT_DIR,
    manifest_path: Path | None = None,
) -> None:
    expected = {relative.as_posix() for relative, _ in release_entries(root, manifest_path)}
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ReleaseError("ZIP contains duplicate paths")
        actual = set(names)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ReleaseError(f"ZIP differs from manifest; missing={missing}, extra={extra}")
        for info in infos:
            relative = PurePosixPath(info.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise ReleaseError(f"Unsafe path in ZIP: {info.filename}")
            reason = _forbidden_path_reason(relative)
            if reason:
                raise ReleaseError(f"Forbidden ZIP entry ({reason}): {info.filename}")
            if not info.filename.isascii() and not (info.flag_bits & 0x800):
                raise ReleaseError(f"Unicode path is missing the UTF-8 flag: {info.filename}")
            _audit_text(info.filename, archive.read(info))


def build_release(
    output: Path,
    root: Path = PROJECT_DIR,
    manifest_path: Path | None = None,
) -> Path:
    root = _absolute(root)
    manifest_path = _absolute(manifest_path or root / "release_manifest.toml")
    output = _absolute(output)
    entries = audit_source(root, manifest_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for relative, source in entries:
                info = zipfile.ZipInfo(relative.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100644 & 0xFFFF) << 16
                archive.writestr(info, source.read_bytes())
        verify_release(temporary, root, manifest_path)
        try:
            os.replace(temporary, output)
        except PermissionError:
            # Some managed Windows sandboxes deny rename/replace in their
            # virtual temp directory while still allowing a new file write.
            # Never use the non-atomic fallback to overwrite an existing ZIP.
            if output.exists():
                raise
            shutil.copyfile(temporary, output)
            temporary.unlink()
    finally:
        if temporary.exists():
            temporary.unlink()
    return output


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _format_entries(entries: Iterable[tuple[PurePosixPath, Path]]) -> str:
    return "\n".join(f"  {relative.as_posix()}" for relative, _ in entries)


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a public TairaSearch ZIP from release_manifest.toml."
    )
    parser.add_argument("--root", type=Path, default=PROJECT_DIR)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Validate allowlisted source files without creating an archive.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_console()
    args = make_parser().parse_args(argv)
    root = _absolute(args.root)
    manifest = args.manifest or root / "release_manifest.toml"
    try:
        entries = audit_source(root, manifest)
        if args.check_only:
            print(f"Public release allowlist is valid ({len(entries)} files):")
            print(_format_entries(entries))
            return 0
        output = build_release(args.output, root, manifest)
    except (OSError, ReleaseError, zipfile.BadZipFile) as exc:
        print(f"Release error: {exc}")
        return 1
    print(f"ZIP created and verified: {output}")
    print(f"Files: {len(entries)}")
    print(f"SHA-256: {sha256_file(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
