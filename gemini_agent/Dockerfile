ARG BUILD_FROM
FROM $BUILD_FROM

# 1. Εγκατάσταση Python
RUN apk add --no-cache python3 py3-pip dos2unix

# 2. Εγκατάσταση Νέας Βιβλιοθήκης Google (google-genai)
RUN pip install requests google-genai pytz python-dateutil --break-system-packages

# 3. Αντιγραφή και Καθαρισμός
COPY agent.py /agent.py
RUN dos2unix /agent.py

# 4. ΕΚΚΙΝΗΣΗ
ENTRYPOINT ["python3", "-u", "/agent.py"]