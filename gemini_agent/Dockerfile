ARG BUILD_FROM
FROM $BUILD_FROM

# Install Python and necessary libraries
RUN apk add --no-cache python3 py3-pip

# Install dependencies for Timezone & AI
RUN pip install requests google-generativeai pytz python-dateutil

# Copy data for add-on
COPY run.sh /
COPY agent.py /

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]