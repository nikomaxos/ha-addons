#!/usr/bin/env bashio
API_KEY=$(bashio::config 'api_key')
WEB_PASS=$(bashio::config 'web_password')

bashio::log.info "Starting AntiWeb UI..."
export GEMINI_API_KEY="$API_KEY"
export PORT=8080
export HOST=0.0.0.0
export BIND=0.0.0.0

# Define HOME for Antigravity (persistent storage)
export HOME="/config/antigravity_home"
mkdir -p "$HOME"

if [ -n "$WEB_PASS" ] && [ "$WEB_PASS" != "null" ]; then
    bashio::log.info "Web password is set by user."
    export ANTIWEB_PASSWORD="$WEB_PASS"
    export ANTIWEB_HTTP_PASSWORD="$WEB_PASS"
    export PASSWORD="$WEB_PASS"
fi

if [ -f /config/configuration.yaml ]; then
    if grep -q "^panel_iframe:" /config/configuration.yaml; then
        if ! grep -q "antigravity:" /config/configuration.yaml; then
            bashio::log.info "Adding antigravity to existing panel_iframe..."
            sed -i '/^panel_iframe:/a \  antigravity:\n    title: '\''AntiWeb AI'\''\n    icon: '\''mdi:robot-outline'\''\n    url: '\''http://homeassistant-oraiokastro:8080'\''\n    require_admin: true' /config/configuration.yaml
        fi
    else
        bashio::log.info "Creating panel_iframe in configuration.yaml..."
        cat >> /config/configuration.yaml <<EOF

panel_iframe:
  antigravity:
    title: 'AntiWeb AI'
    icon: 'mdi:robot-outline'
    url: 'http://homeassistant-oraiokastro:8080'
    require_admin: true
EOF
    fi
fi

exec antiweb --port 8080 --host 0.0.0.0
