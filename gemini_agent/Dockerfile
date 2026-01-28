ARG BUILD_FROM
FROM $BUILD_FROM

# 1. Εγκατάσταση Python
RUN apk add --no-cache python3 py3-pip dos2unix

# 2. Εγκατάσταση Βιβλιοθηκών (με bypass για PEP 668)
RUN pip install requests google-generativeai pytz python-dateutil --break-system-packages

# 3. Αντιγραφή και Καθαρισμός του Agent
COPY agent.py /agent.py
RUN dos2unix /agent.py

# 4. ΕΚΚΙΝΗΣΗ (PURE DOCKER)
# Τρέχουμε απευθείας την Python.
# Το "-u" είναι κρίσιμο για να βλέπεις τα logs αμέσως (χωρίς buffer).
ENTRYPOINT ["python3", "-u", "/agent.py"]