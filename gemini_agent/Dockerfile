FROM python:3.11-alpine

# Εγκατάσταση βασικών εργαλείων (bash, git)
RUN apk add --no-cache bash git

# Εγκατάσταση βιβλιοθηκών Python
RUN pip3 install requests google-generativeai pyyaml --break-system-packages

# Αντιγραφή αρχείων
COPY run.sh /
COPY agent.py /

# Δικαιώματα εκτέλεσης
RUN chmod a+x /run.sh

# Εκκίνηση
CMD [ "/run.sh" ]