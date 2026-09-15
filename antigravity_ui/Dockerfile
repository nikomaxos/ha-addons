ARG BUILD_FROM=ghcr.io/hassio-addons/base:14.0.0
FROM $BUILD_FROM

RUN apk add --no-cache curl \
    && curl -Lo /usr/local/bin/agy "https://storage.googleapis.com/antigravity-releases/latest/agy-linux-amd64" \
    && chmod +x /usr/local/bin/agy

COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
