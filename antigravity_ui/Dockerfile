ARG BUILD_FROM=ghcr.io/hassio-addons/base:14.0.0
FROM $BUILD_FROM

RUN apk add --no-cache curl jq tar gcompat ttyd \
    && URL=$(curl -s https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/linux_amd64.json | jq -r .url) \
    && curl -fsSL "$URL" -o /tmp/cli.tar.gz \
    && tar -xzf /tmp/cli.tar.gz -C /usr/local/bin antigravity \
    && mv /usr/local/bin/antigravity /usr/local/bin/agy \
    && chmod +x /usr/local/bin/agy \
    && rm /tmp/cli.tar.gz

COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
