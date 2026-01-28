ARG BUILD_FROM
FROM $BUILD_FROM

# 1. Εγκατάσταση Python & Tools (Κρατάμε το dos2unix για το agent.py)
RUN apk add --no-cache python3 py3-pip dos2unix

# 2. Εγκατάσταση Βιβλιοθηκών (με bypass για PEP 668)
RUN pip install requests google-generativeai pytz python-dateutil --break-system-packages

# 3. Αντιγραφή ΜΟΝΟ του κώδικα Python
COPY agent.py /

# 4. Διόρθωση του Python αρχείου (για να είμαστε σίγουροι)
RUN dos2unix /agent.py

# 5. ΕΚΚΙΝΗΣΗ: Τρέχουμε απευθείας την Python
# Το "-u" είναι σημαντικό για να βλέπεις τα logs αμέσως (unbuffered)
CMD [ "python3", "-u", "/agent.py" ]