ARG BUILD_FROM
FROM $BUILD_FROM

# 1. Εγκατάσταση Python & Tools
RUN apk add --no-cache python3 py3-pip dos2unix

# 2. Εγκατάσταση Βιβλιοθηκών (με παράκαμψη PEP 668)
RUN pip install requests google-generativeai pytz python-dateutil --break-system-packages

# 3. Αντιγραφή ΜΟΝΟ του κώδικα Python
COPY agent.py /

# Διόρθωση του Python αρχείου από Windows χαρακτήρες (για σιγουριά)
RUN dos2unix /agent.py

# 4. ΔΗΜΙΟΥΡΓΙΑ του run.sh ΕΣΩΤΕΡΙΚΑ (Η Λύση στο πρόβλημα)
# Αυτό αγνοεί το αρχείο των Windows και φτιάχνει ένα φρέσκο, καθαρό Linux script.
RUN echo '#!/usr/bin/with-contenv bashio' > /run.sh && \
    echo 'bashio::log.info "Starting Jarvis AI Professional (v20.0)..."' >> /run.sh && \
    echo 'exec python3 -u /agent.py' >> /run.sh && \
    chmod a+x /run.sh

# 5. Εκκίνηση
CMD [ "/run.sh" ]