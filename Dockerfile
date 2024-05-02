FROM python:3.11

COPY requirements.txt requirements.txt

RUN pip install prospector && \
    pip install -r requirements.txt && \
    useradd -ms /bin/bash jenkins

ENV PATH /home/jenkins/.local/bin:$PATH