"""Publish immutable StarSling workload-cost cards."""

from __future__ import annotations

import os
from typing import Any

from ..publication_contract import (
    PUBLICATION_ROUTE_SCHEMA_VERSION,
    PublicationRoute,
)
from .publication_chart_common import (
    _workload_observed_at,
)
from .publication_metadata import (
    sandbox_workload_publication_metadata,
)
from .publication_sandbox_chart import render_sandbox_workload_publication
from .storage import write_json


from .publication_store import (
    DEFAULT_ARTICLE_URL,
    DEFAULT_PUBLIC_DATA_BASE_URL,
    PUBLICATION_SCHEMA_VERSION,
    _card_publication_contract,
    _join,
    _live_market_card_url,
    _market_card_publication_digest,
    _publish_market_card_state,
)


def publish_sandbox_workload_publication(
    *,
    output_root: str,
    workload_card: dict[str, Any],
    public_base_url: str | None = None,
    article_url: str | None = None,
) -> dict[str, Any]:
    """Publish the latest measured StarSling workload-cost card."""
    public_base = (
        public_base_url
        or os.getenv("COMPUTE_BAZAAR_PUBLIC_BASE_URL")
        or DEFAULT_PUBLIC_DATA_BASE_URL
    ).rstrip("/")
    live_article = (
        article_url or os.getenv("COMPUTE_BAZAAR_ARTICLE_URL") or DEFAULT_ARTICLE_URL
    )
    content_digest = _market_card_publication_digest(
        {"workload": workload_card},
        public_base_url=public_base,
        article_url=live_article,
    )
    observed_at = _workload_observed_at(workload_card)
    link = _publish_market_card_state(
        output_root=output_root,
        public_base_url=public_base,
        card_id="sandbox-cost",
        subject_id="workload",
        view_id="estimated-cost",
        observed_at=observed_at,
        content_digest=content_digest,
        live_url=_live_market_card_url(
            article_url=live_article,
            card_id="sandbox-cost",
            state={},
            anchor="sandbox-benchmark-card",
        ),
        data_url=f"{public_base}/sandbox/workload.json",
        image=render_sandbox_workload_publication(workload_card),
        metadata=sandbox_workload_publication_metadata(
            card=workload_card,
            observed_at=observed_at,
        ),
    )
    workload_card["publication"] = _card_publication_contract(
        card_id="sandbox-cost",
        default_state="cost",
        states={"cost": link},
    )
    revision = PublicationRoute.create(
        card_id="sandbox-cost",
        subject_id="workload",
        view_id="estimated-cost",
        observed_at=observed_at,
        content_digest=content_digest,
    ).revision
    manifest_ref = _join(
        output_root,
        "publications/sandbox-cost/manifest.json",
    )
    publication_rows = [{"state_id": "cost", **link}]
    manifest = {
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "route_schema_version": PUBLICATION_ROUTE_SCHEMA_VERSION,
        "publication_type": "sandbox_workload_cost",
        "revision": revision,
        "publication_count": len(publication_rows),
        "rows": publication_rows,
    }
    write_json(manifest_ref, manifest)
    return {
        "manifest_ref": manifest_ref,
        "revision": revision,
        "publication_count": len(publication_rows),
        "rows": publication_rows,
    }
