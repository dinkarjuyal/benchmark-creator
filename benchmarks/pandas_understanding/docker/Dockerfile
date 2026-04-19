FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_PROGRESS_BAR=off

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

# Install mini-swe-agent + pandas + numpy
RUN python -m pip install --no-cache-dir \
    mini-swe-agent \
    "pandas>=2.0.0,<3.0.0" \
    numpy \
    pyyaml

WORKDIR /work
