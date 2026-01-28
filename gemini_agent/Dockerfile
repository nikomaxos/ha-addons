ARG BUILD_FROM
FROM $BUILD_FROM

# 1. Εγκατάσταση Python
RUN apk add --no-cache python3 py3-pip

# 2. Εγκατάσταση Βιβλιοθηκών (με bypass για PEP 668)
RUN pip install requests google-generativeai pytz python-dateutil --break-system-packages

# 3. Αντιγραφή Python Agent
COPY agent.py /agent.py

# 4. ΔΗΜΙΟΥΡΓΙΑ SERVICE (THE PERMANENT FIX)
# - Δημιουργούμε νέο φάκελο service με μοναδικό όνομα για να σπάσουμε την cache
# - Χρησιμοποιούμε printf για να εγγυηθούμε Linux Line Endings (\n)
# - Χρησιμοποιούμε exec για να τρέξει η Python ως κύριο process
RUN mkdir -p /etc/services.d/jarvis_runner && \
    printf "#!/bin/sh\n\
echo 'Starting Jarvis AI Pro (Native Mode)...'\n\
exec python3 -u /agent.py\n" > /etc/services.d/jarvis_runner/run && \
    chmod +x /etc/services.d/jarvis_runner/run