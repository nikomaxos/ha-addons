ARG BUILD_FROM
FROM $BUILD_FROM

# 1. Εγκατάσταση Python & Tools
RUN apk add --no-cache python3 py3-pip dos2unix

# 2. Εγκατάσταση Βιβλιοθηκών (με bypass για PEP 668)
RUN pip install requests google-generativeai pytz python-dateutil --break-system-packages

# 3. Αντιγραφή του κώδικα Python
COPY agent.py /

# 4. Διόρθωση του Python αρχείου (για να είμαστε 100% σίγουροι)
RUN dos2unix /agent.py

# 5. ΔΗΜΙΟΥΡΓΙΑ RUN SCRIPT (BARE METAL VERSION)
# Αφαιρέσαμε το 'with-contenv bashio'. Τώρα είναι απλό Linux script.
# Δεν θα κρασάρει ποτέ με PID 1 error.
RUN mkdir -p /etc/services.d/jarvis && \
    echo '#!/bin/bash' > /etc/services.d/jarvis/run && \
    echo 'echo "Starting Jarvis AI Professional (v20.0)..."' >> /etc/services.d/jarvis/run && \
    echo 'exec python3 -u /agent.py' >> /etc/services.d/jarvis/run && \
    chmod +x /etc/services.d/jarvis/run