ARG BUILD_FROM=ghcr.io/hassio-addons/debian-base:7.3.3
FROM $BUILD_FROM

RUN apt-get update && apt-get install -y curl jq tar ttyd \
    && URL=$(curl -s https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/linux_amd64.json | jq -r .url) \
    && curl -fsSL "$URL" -o /tmp/cli.tar.gz \
    && tar -xzf /tmp/cli.tar.gz -C /usr/local/bin antigravity \
    && mv /usr/local/bin/antigravity /usr/local/bin/agy \
    && chmod +x /usr/local/bin/agy \
    && rm /tmp/cli.tar.gz \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY run.sh /
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
