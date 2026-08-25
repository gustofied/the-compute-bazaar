# Public feed on GitHub Pages

The live public feed is built hourly by
`.github/workflows/public-feed-pages.yml` and served by GitHub Pages at
`https://bazaar.adamsioud.com`.

The workflow runs the public provider pipeline, publishes market cards and the
sanitized portable lake, and deploys one static artifact. The article keeps its
own committed snapshots as fallbacks. A GitHub Actions cache carries the public
market history from one hourly run to the next. Bronze and private deal data are
never published.

## Repository settings

In **Settings → Pages**, set **Build and deployment → Source** to **GitHub
Actions**. Set the custom domain to `bazaar.adamsioud.com`.

At the DNS provider, replace the old CloudFront record with:

```text
Type   Host     Value
CNAME  bazaar   gustofied.github.io
```

The Pages artifact includes `CNAME` and `.nojekyll`. The latter is required
because the portable lake contains underscore-prefixed paths.

## Local build

```bash
uv sync --frozen --extra worker
uv run python -m the_compute_bazaar.pages_feed \
  --output-root _site \
  --raw-root .market-state/raw \
  --lake-root .market-state/lake
```

The old CloudFront distribution and S3 bucket were deleted on August 21, 2026.
The AWS configuration under `infra/aws/public-feed/` remains only as a record
of the previous deployment.
