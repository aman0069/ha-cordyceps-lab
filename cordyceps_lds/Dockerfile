# Cordyceps Lab Data Service — Home Assistant App (formerly "add-on")
#
# IMPORTANT (Supervisor >= 2026.04.0):
#   Supervisor no longer injects the BUILD_FROM argument and no longer reads
#   build.yaml. The base image MUST be declared with an explicit FROM here.
#   Reference: https://developers.home-assistant.io/docs/apps/configuration
#
#   We use the MULTI-ARCH Home Assistant base image so this builds unchanged on
#   amd64 (NUC/VM) and aarch64 (Raspberry Pi 4/5, ODROID). Do not pin this back
#   to a {arch}- prefixed image — that is what broke portability before.
#
#   TAG FORMAT: <alpine-version>-<base-build-version>, e.g. 3.24-2026.08.0.
#   There is NO bare "2026.08.0" tag. Do not assume the tag matches the Home
#   Assistant Core release number — verify against the registry:
#     https://github.com/home-assistant/docker-base/pkgs/container/base
#   This tag resolves to alpine:3.24 with S6 Overlay v3 (entrypoint /init),
#   published for linux/amd64 and linux/arm64 only.
FROM ghcr.io/home-assistant/base:3.24-2026.08.0

# BUILD_ARCH / BUILD_VERSION are the only args Supervisor still provides.
ARG BUILD_ARCH="amd64"
ARG BUILD_VERSION="2.5.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# The HA base image is Alpine and ships bashio + tzdata but not Python.
# Alpine's Python is PEP-668 "externally managed", so we build in a venv
# rather than fighting pip with --break-system-packages.
RUN apk add --no-cache python3 py3-pip bash tzdata \
    && python3 -m venv "$VIRTUAL_ENV"

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY run.sh /run.sh
RUN chmod a+x /run.sh

# Required when the image is not built by the Home Assistant builder action.
LABEL \
    io.hass.name="Cordyceps Lab Data Service" \
    io.hass.description="FastAPI + SQLite batch/jar tracking service for the Cordyceps lab" \
    io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}" \
    io.hass.url="https://github.com/aman0069/ha-cordyceps-lab"

CMD [ "/run.sh" ]
