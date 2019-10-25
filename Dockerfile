FROM python:3.7-buster
# NOTE: This file is not used for deployment. We only have it so that
# docker-compose uses the right image and builds the web container.
COPY requirements.txt /app/
WORKDIR /app
RUN pip3 install -r requirements.txt
