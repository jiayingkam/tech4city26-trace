FROM python:3.12-slim

WORKDIR /service
# old one
# RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg && \
#     curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - && \
#     curl https://packages.microsoft.com/config/debian/12/prod.list \
#         > /etc/apt/sources.list.d/mssql-release.list && \
#     apt-get update && \
#     ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc-dev && \
#     apt-get clean && rm -rf /var/lib/apt/lists/*
# below is the updated one:
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg ca-certificates && \
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
      > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY atomic/content_drafts/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/trace_auth trace_auth/
COPY atomic/content_drafts/app/ app/

ENV FLASK_APP=app.app:create_app
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5002

CMD ["flask", "run"]