#!/usr/bin/env bashio
API_KEY=$(bashio::config 'api_key')
WEB_PASS=$(bashio::config 'web_password')

bashio::log.info "Starting AntiWeb UI..."
export GEMINI_API_KEY="$API_KEY"
export PORT=8080
export HOST=0.0.0.0
export BIND=0.0.0.0

if [ -n "$WEB_PASS" ] && [ "$WEB_PASS" != "null" ]; then
    bashio::log.info "Web password is set by user."
    export ANTIWEB_PASSWORD="$WEB_PASS"
    export ANTIWEB_HTTP_PASSWORD="$WEB_PASS"
    export PASSWORD="$WEB_PASS"
fi

exec antiweb --port 8080 --host 0.0.0.0
