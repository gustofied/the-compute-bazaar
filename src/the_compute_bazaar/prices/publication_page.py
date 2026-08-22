"""Crawler-readable HTML shell for immutable market-card publications."""

from __future__ import annotations

import json
from collections.abc import Mapping
from html import escape
from typing import Any

from .publication_chart_common import IMAGE_HEIGHT, IMAGE_WIDTH


def publication_html(metadata: Mapping[str, Any]) -> str:
    title = escape(str(metadata["title"]))
    description = escape(str(metadata["description"]))
    page_url = escape(str(metadata["page_url"]), quote=True)
    image_url = escape(str(metadata["image_url"]), quote=True)
    live_url = escape(str(metadata["live_url"]), quote=True)
    data_url = escape(str(metadata["data_url"]), quote=True)
    image_alt = escape(str(metadata["image_alt"]), quote=True)
    render_profile = escape(
        str(metadata.get("render_profile") or "unknown"), quote=True
    )
    renderer_revision = escape(
        str(metadata.get("renderer_revision") or "unknown"), quote=True
    )
    footer_label = escape(
        str(
            metadata.get("footer_label")
            or " / ".join(
                (
                    str(metadata.get("family_id") or ""),
                    str(metadata.get("range_label") or ""),
                    str(metadata.get("change_label") or "").lower(),
                    str(metadata.get("observed_label") or "").lower(),
                )
            ).strip(" /")
        )
    )
    redirect_url = json.dumps(str(metadata["live_url"])).replace("<", "\\u003c")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <meta name="compute-bazaar:render-profile" content="{render_profile}">
  <meta name="compute-bazaar:renderer-revision" content="{renderer_revision}">
  <link rel="canonical" href="{page_url}">
  <meta property="og:title" content="{title}">
  <meta property="og:type" content="article">
  <meta property="og:site_name" content="Compute Bazaar">
  <meta property="og:url" content="{page_url}">
  <meta property="og:description" content="{description}">
  <meta property="og:image" content="{image_url}">
  <meta property="og:image:secure_url" content="{image_url}">
  <meta property="og:image:type" content="image/png">
  <meta property="og:image:width" content="{IMAGE_WIDTH}">
  <meta property="og:image:height" content="{IMAGE_HEIGHT}">
  <meta property="og:image:alt" content="{image_alt}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:url" content="{page_url}">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{description}">
  <meta name="twitter:image" content="{image_url}">
  <meta name="twitter:image:alt" content="{image_alt}">
  <script>
    window.location.replace({redirect_url});
  </script>
  <style>
    :root {{
      color-scheme: light;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      background: #efede4;
      color: #142027;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      min-height: 100vh;
      margin: 0;
      display: grid;
      place-items: center;
      padding: clamp(18px, 5vw, 72px);
      background: #efede4;
    }}
    main {{ width: min(1200px, 100%); }}
    a.preview {{
      display: block;
      border: 1px solid #a7b1b3;
      background: #f8f5eb;
      box-shadow: 0 24px 70px rgb(20 32 39 / 12%);
    }}
    img {{ display: block; width: 100%; height: auto; }}
    footer {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: baseline;
      padding-top: 14px;
      font-size: 13px;
    }}
    footer p {{ margin: 0; color: #5f6f76; }}
    footer nav {{ display: flex; gap: 16px; }}
    footer a {{ color: #315f82; text-underline-offset: 3px; }}
    @media (max-width: 620px) {{
      body {{ padding: 12px; }}
      footer {{ align-items: flex-start; flex-direction: column; }}
    }}
  </style>
</head>
<body>
  <main>
    <a class="preview" href="{live_url}" aria-label="Open the interactive card">
      <img src="{image_url}" width="{IMAGE_WIDTH}" height="{IMAGE_HEIGHT}" alt="{image_alt}">
    </a>
    <footer>
      <p>{footer_label}</p>
      <nav aria-label="Publication links">
        <a href="{live_url}">Open interactive card</a>
        <a href="{data_url}">Open data</a>
      </nav>
    </footer>
  </main>
</body>
</html>
"""
