#!/usr/bin/env bashio
API_KEY=$(bashio::config 'api_key')
bashio::log.info "Starting Google Antigravity Web UI (via ttyd)..."
export GEMINI_API_KEY="$API_KEY"
export TERM=xterm-256color
export COLORTERM=truecolor
exec ttyd -p 8080 -W /usr/local/bin/agy
