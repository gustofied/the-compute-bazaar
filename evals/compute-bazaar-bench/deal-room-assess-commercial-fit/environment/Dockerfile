FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        asciinema=2.2.0-1 \
        tmux=3.3a-3 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash agent \
    && mkdir -p /workspace/matter /workspace/output \
    && chown -R agent:agent /workspace/output

COPY matter/ /workspace/matter/
COPY output-schema.json /workspace/output-schema.json

RUN find /workspace/matter -type d -exec chmod 0555 {} + \
    && find /workspace/matter -type f -exec chmod 0444 {} + \
    && chmod 0444 /workspace/output-schema.json \
    && chmod 0755 /workspace /workspace/output

WORKDIR /workspace
