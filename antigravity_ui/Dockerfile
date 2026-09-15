ARG BUILD_FROM=ghcr.io/hassio-addons/base:14.0.0
FROM $BUILD_FROM

RUN apk add --no-cache curl bash \
    && curl -fsSL https://antigravity.google/cli/install.sh | bash -s -- -d /usr/local/bin

COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
