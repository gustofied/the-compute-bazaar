FROM ubuntu:24.04

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Tools for reading the matter files and producing the required DOCX.
RUN apt-get update && apt-get install -y --no-install-recommends \
        pandoc python3 python3-pip ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && uv pip install --system --break-system-packages \
        openpyxl python-docx

WORKDIR /app

COPY documents/ /app/documents/
