#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Jarvis AI Professional (v20.0)..."
bashio::log.info "Initializing System..."

# Εκτέλεση του python script με Unbuffered output (-u) για να βλέπεις τα logs αμέσως
exec python3 -u /agent.py