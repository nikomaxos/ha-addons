#!/usr/bin/env bashio
API_KEY=$(bashio::config 'api_key')
bashio::log.info "Starting Google Antigravity Web UI..."
export GEMINI_API_KEY="$API_KEY"
exec /usr/local/bin/agy serve-web --port 8080 --host 0.0.0.0
