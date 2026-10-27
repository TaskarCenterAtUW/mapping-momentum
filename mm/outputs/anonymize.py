"""Anonymize participant identities in report statistics."""

from __future__ import annotations

import re
from typing import Any, TypeGuard


def _is_report_object(value: Any) -> TypeGuard[dict[str, Any]]:
    """Return whether *value* is a report mapping."""
    return isinstance(value, dict)


def _is_report_list(value: Any) -> TypeGuard[list[Any]]:
    """Return whether *value* is a report list."""
    return isinstance(value, list)


def anonymize_stats(stats: dict[str, Any]) -> dict[str, Any]:
    """Return report stats with participant names replaced by stable labels.

    Contributor usernames, marker authors and edit histories, and quote
    attributions share labels in the order they first appear. Known names are
    also replaced at whole-word boundaries in note and quote text.
    """
    labels: dict[str, str] = {}
    used_numbers: set[int] = set()
    next_number = 1

    def label_for(name: Any) -> Any:
        """Return a stable anonymous label for a non-empty identity name."""
        nonlocal next_number
        if not isinstance(name, str) or not name.strip():
            return name
        if name in labels:
            return labels[name]

        parts = name.split()
        if (
            len(parts) == 2
            and parts[0] == "Participant"
            and parts[1].isdigit()
            and int(parts[1]) not in used_numbers
        ):
            number = int(parts[1])
            label = name
        else:
            while next_number in used_numbers:
                next_number += 1
            number = next_number
            label = f"Participant {number}"
            next_number += 1
        labels[name] = label
        used_numbers.add(number)
        return label

    def quote_name(quote: dict[str, Any]) -> str:
        """Combine the available first and last name fields for a quote."""
        parts = [
            value.strip()
            for value in (quote.get("first_name"), quote.get("last_name"))
            if isinstance(value, str) and value.strip()
        ]
        return " ".join(parts)

    contributors = stats.get("contributors_breakdown")
    contributions_by_user = stats.get("contributions_by_user")
    markers = stats.get("markers")
    quotes = stats.get("quotes")

    if _is_report_list(contributors):
        for contributor in contributors:
            if _is_report_object(contributor):
                label_for(contributor.get("user"))

    if _is_report_list(contributions_by_user):
        for contribution in contributions_by_user:
            if _is_report_object(contribution):
                label_for(contribution.get("user"))

    if _is_report_list(markers):
        for marker in markers:
            if not _is_report_object(marker):
                continue
            label_for(marker.get("user"))
            versions = marker.get("versions")
            if _is_report_list(versions):
                for version in versions:
                    if _is_report_object(version):
                        label_for(version.get("user"))

    if _is_report_list(quotes):
        for quote in quotes:
            if _is_report_object(quote):
                label_for(quote_name(quote))

    text_names = sorted(
        ((name, label) for name, label in labels.items() if name != label),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    text_pattern = (
        re.compile(
            r"(?<!\w)(?:"
            + "|".join(re.escape(name) for name, _label in text_names)
            + r")(?!\w)",
            re.IGNORECASE,
        )
        if text_names
        else None
    )
    text_labels: dict[str, str] = {}
    for name, label in text_names:
        text_labels.setdefault(name.casefold(), label)

    def replace_known_names(value: Any) -> Any:
        """Replace known identity names in a free-form text value."""
        if not isinstance(value, str) or text_pattern is None:
            return value
        return text_pattern.sub(
            lambda match: text_labels[match.group(0).casefold()], value
        )

    anonymized = dict(stats)
    if _is_report_list(contributors):
        anonymized_contributors: list[Any] = []
        anonymized["contributors_breakdown"] = anonymized_contributors
        for contributor in contributors:
            if not _is_report_object(contributor):
                anonymized_contributors.append(contributor)
                continue
            item = dict(contributor)
            if "user" in item:
                item["user"] = label_for(item["user"])
            anonymized_contributors.append(item)

    if _is_report_list(contributions_by_user):
        anonymized_contributions: list[Any] = []
        anonymized["contributions_by_user"] = anonymized_contributions
        for contribution in contributions_by_user:
            if not _is_report_object(contribution):
                anonymized_contributions.append(contribution)
                continue
            item = dict(contribution)
            if "user" in item:
                item["user"] = label_for(item["user"])
            anonymized_contributions.append(item)

    if _is_report_list(markers):
        anonymized_markers: list[Any] = []
        anonymized["markers"] = anonymized_markers
        for marker in markers:
            if not _is_report_object(marker):
                anonymized_markers.append(marker)
                continue
            item = dict(marker)
            if "user" in item:
                item["user"] = label_for(item["user"])
            if "text" in item:
                item["text"] = replace_known_names(item["text"])

            versions = marker.get("versions")
            if _is_report_list(versions):
                anonymized_versions: list[Any] = []
                item["versions"] = anonymized_versions
                for version in versions:
                    if not _is_report_object(version):
                        anonymized_versions.append(version)
                        continue
                    version_item = dict(version)
                    if "user" in version_item:
                        version_item["user"] = label_for(version_item["user"])
                    anonymized_versions.append(version_item)
            anonymized_markers.append(item)

    if _is_report_list(quotes):
        anonymized_quotes: list[Any] = []
        anonymized["quotes"] = anonymized_quotes
        for quote in quotes:
            if not _is_report_object(quote):
                anonymized_quotes.append(quote)
                continue
            item = dict(quote)
            name = quote_name(quote)
            if name:
                item["first_name"] = label_for(name)
                item["last_name"] = ""
            for field in ("text", "organization", "title"):
                if field in item:
                    item[field] = replace_known_names(item[field])
            anonymized_quotes.append(item)

    anonymized["anonymized"] = True
    return anonymized
