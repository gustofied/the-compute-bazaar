FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asciinema=2.2.0-1 \
        tmux=3.3a-3 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash agent \
    && mkdir -p /opt/market /workspace \
    && chown agent:agent /workspace \
    && chmod 0755 /opt/market

COPY market_cli.py entrypoint.sh /opt/market/

RUN install -m 0755 /opt/market/market_cli.py /usr/local/bin/market \
    && chmod 0755 /opt/market/entrypoint.sh

ENV MARKET_URL=http://market:8000
WORKDIR /workspace

ENTRYPOINT ["/opt/market/entrypoint.sh"]
