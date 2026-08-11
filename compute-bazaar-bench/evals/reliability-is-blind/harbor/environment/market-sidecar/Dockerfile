FROM python:3.13.7-slim-bookworm@sha256:adafcc17694d715c905b4c7bebd96907a1fd5cf183395f0ebc4d3428bd22d92d

RUN useradd --system --create-home --shell /usr/sbin/nologin market \
    && mkdir -p /opt/market /var/lib/market /market-artifacts \
    && chown -R market:market /var/lib/market /market-artifacts

COPY server.py snapshot.py market_engine.py /opt/market/

RUN chmod 0555 \
        /opt/market/server.py \
        /opt/market/snapshot.py \
        /opt/market/market_engine.py

USER market
WORKDIR /opt/market

ENTRYPOINT ["python3", "/opt/market/server.py"]
