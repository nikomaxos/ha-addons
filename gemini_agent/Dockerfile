ARG BUILD_FROM
FROM $BUILD_FROM

# Setup Environment
ENV LANG C.UTF-8
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Install Dependencies
RUN apk add --no-cache python3 py3-pip git

# Install Libraries (Force google-genai upgrade)
RUN pip install requests pytz python-dateutil google-genai --break-system-packages

# Copy Agent
COPY agent.py /agent.py

# Entrypoint (Direct Execution)
ENTRYPOINT ["python3", "/agent.py"]