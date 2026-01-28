ARG BUILD_FROM
FROM $BUILD_FROM

# 1. Install Python, pip AND dos2unix (για διόρθωση Windows αρχείων)
RUN apk add --no-cache python3 py3-pip dos2unix

# 2. Install Dependencies (bypass PEP 668 restrictions)
RUN pip install requests google-generativeai pytz python-dateutil --break-system-packages

# 3. Copy τα αρχεία
COPY run.sh /
COPY agent.py /

# 4. FIX Windows Line Endings & Permissions (Η ΛΥΣΗ ΣΤΟ ΠΡΟΒΛΗΜΑ ΣΟΥ)
# Το dos2unix θα καθαρίσει τους κρυφούς χαρακτήρες από το run.sh και το agent.py
RUN dos2unix /run.sh && \
    dos2unix /agent.py && \
    chmod a+x /run.sh

# 5. Start
CMD [ "/run.sh" ]