#!/usr/bin/env python3
"""Verify license metadata for the exact pg8000 candidate wheel closure.

Artifact hashes prove which wheels were downloaded, but they do not prove that
every transitive package satisfies the repository's commercial inbound-license
policy. This verifier reads METADATA directly from the already hash-verified
wheels, requires the exact reviewed package/version set, rejects GPL-family
metadata, and requires positive permissive-license evidence for every wheel.
It never imports or executes candidate package code.
"""

from __future__ import annotations

from email.parser import Parser
from pathlib import Path
import re
import sys
import zipfile


_MAX_METADATA_BYTES = 524_288
_CANONICAL_NAME_SEPARATOR = re.compile(r"[-_.]+")
_GPL_FAMILY = re.compile(r"(?:^|[^a-z])(agpl|lgpl|gpl)(?:[^a-z]|$)")

_EXPECTED_WHEELS = {
    "pg8000-1.31.5-py3-none-any.whl": (
        "pg8000",
        "1.31.5",
        ("bsd",),
    ),
    "python_dateutil-2.9.0.post0-py2.py3-none-any.whl": (
        "python-dateutil",
        "2.9.0.post0",
        ("apache software license", "bsd license"),
    ),
    "scramp-1.4.17-py3-none-any.whl": (
        "scramp",
        "1.4.17",
        ("mit-0", "mit no attribution", "mit no attribution license"),
    ),
    "asn1crypto-1.5.1-py2.py3-none-any.whl": (
        "asn1crypto",
        "1.5.1",
        ("mit",),
    ),
    "six-1.17.0-py2.py3-none-any.whl": (
        "six",
        "1.17.0",
        ("mit",),
    ),
}


class CandidateWheelLicenseError(RuntimeError):
    """Reject candidate metadata that cannot support commercial admission."""


def _canonical_distribution_name(value: str) -> str:
    """Apply the package-name normalization used for exact identity comparison."""
    return _CANONICAL_NAME_SEPARATOR.sub("-", value).casefold()


def _read_metadata(wheel_path: Path) -> str:
    """Read one bounded wheel METADATA member without extracting package code."""
    try:
        with zipfile.ZipFile(wheel_path) as archive:
            metadata_members = [
                info
                for info in archive.infolist()
                if info.filename.endswith(".dist-info/METADATA")
            ]
            if len(metadata_members) != 1:
                raise CandidateWheelLicenseError(
                    "candidate wheel metadata identity is invalid"
                )
            metadata_member = metadata_members[0]
            if metadata_member.file_size > _MAX_METADATA_BYTES:
                raise CandidateWheelLicenseError(
                    "candidate wheel metadata exceeds the bounded evidence size"
                )
            raw_metadata = archive.read(metadata_member)
    except (OSError, zipfile.BadZipFile, RuntimeError):
        raise CandidateWheelLicenseError("candidate wheel could not be inspected") from None

    if len(raw_metadata) > _MAX_METADATA_BYTES:
        raise CandidateWheelLicenseError(
            "candidate wheel metadata exceeds the bounded evidence size"
        )
    try:
        return raw_metadata.decode("utf-8")
    except UnicodeDecodeError:
        raise CandidateWheelLicenseError("candidate wheel metadata is not UTF-8") from None


def _license_evidence(metadata_text: str) -> tuple[str, ...]:
    """Collect declared license fields and classifiers as separate evidence lines."""
    message = Parser().parsestr(metadata_text)
    evidence_values: list[str] = []
    for header in ("License-Expression", "License"):
        value = message.get(header)
        if value:
            evidence_values.append(value.casefold())
    evidence_values.extend(
        classifier.casefold()
        for classifier in message.get_all("Classifier", [])
        if classifier.casefold().startswith("license ::")
    )
    return tuple(evidence_values)


def _contains_marker(evidence_lines: tuple[str, ...], marker: str) -> bool:
    """Match one approved marker on non-alphanumeric boundaries only.

    License metadata is untrusted decision input. Substring matching would accept
    an unrelated word such as ``limited`` for the reviewed ``MIT`` marker. The
    boundary check still accepts SPDX identifiers and classifier phrases while
    preventing a permissive token from being smuggled inside another word.
    """
    marker_pattern = re.compile(
        rf"(?<![a-z0-9]){re.escape(marker.casefold())}(?![a-z0-9])"
    )
    return any(marker_pattern.search(line) is not None for line in evidence_lines)


def _verify_one_wheel(
    wheel_path: Path,
    *,
    expected_name: str,
    expected_version: str,
    approved_markers: tuple[str, ...],
) -> None:
    """Validate exact package identity and positive/negative license evidence."""
    metadata_text = _read_metadata(wheel_path)
    message = Parser().parsestr(metadata_text)
    package_name = message.get("Name")
    package_version = message.get("Version")
    if (
        type(package_name) is not str
        or _canonical_distribution_name(package_name) != expected_name
        or type(package_version) is not str
        or package_version != expected_version
    ):
        raise CandidateWheelLicenseError("candidate wheel package identity is invalid")

    license_evidence = _license_evidence(metadata_text)
    if not license_evidence:
        raise CandidateWheelLicenseError(
            "candidate wheel lacks approved license evidence"
        )
    joined_evidence = "\n".join(license_evidence)
    if (
        _GPL_FAMILY.search(joined_evidence) is not None
        or "gnu general public license" in joined_evidence
        or "gnu lesser general public license" in joined_evidence
        or "gnu affero general public license" in joined_evidence
    ):
        raise CandidateWheelLicenseError(
            "candidate wheel contains a disallowed license"
        )
    if not any(
        _contains_marker(license_evidence, marker) for marker in approved_markers
    ):
        raise CandidateWheelLicenseError(
            "candidate wheel lacks approved license evidence"
        )


def verify_candidate_wheel_licenses(directory: Path) -> None:
    """Verify the exact immutable pg8000 candidate closure in ``directory``.

    The directory is expected to contain only the five wheel artifacts that the
    CI digest gate pins and later installs with ``--no-deps``. Requiring the same
    exact set prevents an unreviewed extra artifact from entering license evidence
    without a corresponding digest and policy decision.
    """
    if type(directory) is not Path or not directory.is_dir():
        raise CandidateWheelLicenseError("candidate wheel directory is invalid")
    wheel_names = {path.name for path in directory.glob("*.whl")}
    if wheel_names != set(_EXPECTED_WHEELS):
        raise CandidateWheelLicenseError("candidate wheel set is invalid")

    for filename, (package_name, package_version, approved_markers) in sorted(
        _EXPECTED_WHEELS.items()
    ):
        _verify_one_wheel(
            directory / filename,
            expected_name=package_name,
            expected_version=package_version,
            approved_markers=approved_markers,
        )


def main(argv: list[str] | None = None) -> int:
    """Run license admission against one exact candidate wheel directory."""
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        raise SystemExit("usage: verify_candidate_wheel_licenses.py WHEEL_DIRECTORY")
    try:
        verify_candidate_wheel_licenses(Path(arguments[0]))
    except CandidateWheelLicenseError as exc:
        raise SystemExit(str(exc)) from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
