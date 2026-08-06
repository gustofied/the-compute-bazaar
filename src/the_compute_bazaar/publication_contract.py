"""Shared identity and routing contract for immutable public card snapshots."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .contracts import PUBLICATION_ROUTE_CONTRACT

_SEGMENT_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class PublicationRoute:
    """A human-readable route whose final segment remains content-addressed."""

    card_id: str
    subject_id: str
    view_id: str
    revision: str

    @classmethod
    def create(
        cls,
        *,
        card_id: str,
        subject_id: str,
        view_id: str,
        observed_at: datetime | None,
        content_digest: str,
    ) -> PublicationRoute:
        digest = _segment(content_digest)[:10]
        normalized_observed_at = observed_at
        if normalized_observed_at and normalized_observed_at.tzinfo is None:
            normalized_observed_at = normalized_observed_at.replace(tzinfo=timezone.utc)
        timestamp = (
            normalized_observed_at.astimezone(timezone.utc).strftime(
                "%Y-%m-%d-%H%M-utc"
            )
            if normalized_observed_at
            else "undated"
        )
        return cls(
            card_id=_segment(card_id),
            subject_id=_segment(subject_id),
            view_id=_segment(view_id),
            revision=f"{timestamp}-{digest}",
        )

    @property
    def publication_id(self) -> str:
        return ":".join((self.card_id, self.subject_id, self.view_id, self.revision))

    @property
    def prefix(self) -> str:
        return "/".join(
            (
                "publications",
                self.card_id,
                self.subject_id,
                self.view_id,
                self.revision,
            )
        )

    @property
    def public_path(self) -> str:
        """Return the canonical extensionless path exposed through CloudFront."""
        return self.prefix

    @property
    def page_path(self) -> str:
        """Return the physical HTML object path stored in S3."""
        return f"{self.prefix}.html"

    @property
    def image_path(self) -> str:
        return f"{self.prefix}.png"

    def as_dict(self) -> dict[str, str]:
        return {
            "contract": PUBLICATION_ROUTE_CONTRACT,
            "card_id": self.card_id,
            "subject_id": self.subject_id,
            "view_id": self.view_id,
            "revision": self.revision,
            "publication_id": self.publication_id,
            "public_path": self.public_path,
            "page_object_path": self.page_path,
            "image_path": self.image_path,
        }


def _segment(value: str) -> str:
    segment = _SEGMENT_PATTERN.sub("-", str(value).lower()).strip("-")
    if not segment:
        raise ValueError("Publication route segments cannot be empty")
    return segment
