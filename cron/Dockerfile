FROM python:3.10-buster

RUN wget -c https://fastdl.mongodb.org/tools/db/mongodb-database-tools-debian10-x86_64-100.6.0.deb && apt install ./mongodb-database-tools*.deb && rm mongodb-database-tools*.deb
COPY ./requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ./ .
CMD python scripts/cron.py
