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

# 5. ΔΗΜΙΟΥΡΓΙΑ SERVICE (Με νέο όνομα 'gemini_service' για να αποφύγουμε την cache)
# Χρησιμοποιούμε /bin/sh που είναι native στο Alpine Linux.
RUN mkdir -p /etc/services.d/gemini_service && \
    printf "#!/bin/sh\necho 'Starting Jarvis AI Pro (Clean Service)...'\nexec python3 -u /agent.py\n" > /etc/services.d/gemini_service/run && \
    chmod +x /etc/services.d/gemini_service/run