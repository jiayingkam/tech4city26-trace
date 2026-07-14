FROM python:3.12-slim

WORKDIR /service

RUN pip install --no-cache-dir python-tds certifi "pyOpenSSL<24"

COPY healthcheck.py .

CMD ["tail", "-f", "/dev/null"]
