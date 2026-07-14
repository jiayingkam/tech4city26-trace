FROM python:3.12-slim

WORKDIR /service

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY run_smoke_test.py .

CMD ["python", "run_smoke_test.py"]
