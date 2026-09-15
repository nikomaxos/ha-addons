#!/usr/bin/env bashio
API_KEY=$(bashio::config 'api_key')
bashio::log.info "Starting AntiWeb UI..."
export GEMINI_API_KEY="$API_KEY"
export PORT=8080
export HOST=0.0.0.0
export BIND=0.0.0.0
exec antiweb --port 8080 --host 0.0.0.0
