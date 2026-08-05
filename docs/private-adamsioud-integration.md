# Private AdamSioud Integration

The public Compute Bazaar repository can be installed, tested, and operated
without the AdamSioud website. The website is an optional private integration
recorded as the `external/AdamSioud` Git submodule.

The normal public workflow does not initialize the submodule:

```sh
git clone https://github.com/gustofied/the-compute-bazaar.git
cd the-compute-bazaar
uv sync --locked
uv run python -m unittest discover -s tests -v
```

Users with access to the private AdamSioud repository can enable the article
integration explicitly:

```sh
git submodule update --init --depth 1 external/AdamSioud
uv run compute-bazaar-adamsioud
```

The public backend, provider ingestion, DataFusion queries, sandbox benchmark,
Windmill jobs, S3 lake, and CloudFront publication payloads must not import or
depend on the private website checkout.
