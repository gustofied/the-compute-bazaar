"""Publish immutable StarSling workload-cost cards."""

from __future__ import annotations

import os
from typing import Any

from ..contracts import (
    PUBLICATION_CONTRACT,
    PUBLICATION_ROUTE_CONTRACT,
)
from ..publication_contract import PublicationRoute
from .publication_chart_common import (
    _workload_observed_at,
)
from .publication_metadata import (
    sandbox_workload_publication_metadata,
)
from .publication_profiles import WORKLOAD_PUBLICATION_RENDER_PROFILE
from .publication_sandbox_chart import render_sandbox_workload_publication
from .storage import write_json


from .publication_store import (
    DEFAULT_ARTICLE_URL,
    configured_public_base_url,
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
    public_base = configured_public_base_url(public_base_url)
    if not public_base:
        raise ValueError("A public base URL is required to publish immutable cards")
    live_article = (
        article_url or os.getenv("COMPUTE_BAZAAR_ARTICLE_URL") or DEFAULT_ARTICLE_URL
    )
    content_digest = _market_card_publication_digest(
        {"workload": workload_card},
        public_base_url=public_base,
        article_url=live_article,
        render_profile=WORKLOAD_PUBLICATION_RENDER_PROFILE,
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
        render_profile=WORKLOAD_PUBLICATION_RENDER_PROFILE,
    )
    workload_card["publication"] = _card_publication_contract(
        card_id="sandbox-cost",
        default_state="cost",
        states={"cost": link},
        render_profile=WORKLOAD_PUBLICATION_RENDER_PROFILE,
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
        "contract": PUBLICATION_CONTRACT,
        "route_contract": PUBLICATION_ROUTE_CONTRACT,
        "publication_type": "sandbox_workload_cost",
        "render_profile": WORKLOAD_PUBLICATION_RENDER_PROFILE,
        "renderer_revision": link["renderer_revision"],
        "revision": revision,
        "publication_count": len(publication_rows),
        "rows": publication_rows,
    }
    write_json(manifest_ref, manifest)
    return {
        "manifest_ref": manifest_ref,
        "revision": revision,
        "render_profile": WORKLOAD_PUBLICATION_RENDER_PROFILE,
        "renderer_revision": link["renderer_revision"],
        "publication_count": len(publication_rows),
        "rows": publication_rows,
    }
