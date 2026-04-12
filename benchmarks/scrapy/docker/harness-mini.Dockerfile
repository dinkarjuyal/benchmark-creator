FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_PROGRESS_BAR=off

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir \
    mini-swe-agent \
    pyyaml \
    hatchling \
    editables \
    pytest \
    "Twisted>=21.7.0,<=25.5.0" \
    cryptography \
    cssselect \
    defusedxml \
    itemadapter \
    itemloaders \
    lxml \
    packaging \
    parsel \
    protego \
    pyOpenSSL \
    queuelib \
    service_identity \
    tldextract \
    w3lib \
    zope.interface \
    PyDispatcher

WORKDIR /work
