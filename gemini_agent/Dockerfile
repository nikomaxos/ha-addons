ARG BUILD_FROM
FROM $BUILD_FROM

# Install Python and Git
RUN apk add --no-cache python3 py3-pip git

# Install libraries
RUN pip3 install requests google-generativeai pyyaml --break-system-packages

COPY run.sh /
COPY agent.py /

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
