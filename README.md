# Tech4City 2026 — Trace

A microservices backend built with Flask, organised into **atomic** (CRUD) and **composite** (orchestration) services.

---

## Service Port Mappings (Not finalised)

| Port | Service                   | Type      |
| ---- | ------------------------- | --------- |
| 5000 | Swagger Docs UI           | docs      |
| 5001 | Users                     | atomic    |
| 5002 | Content Drafts            | atomic    |
| 5003 | Detections                | atomic    |
| 5004 | Edits                     | atomic    |
| 5005 | Exposure Profiles         | atomic    |
| 5006 | Quarantine Items          | atomic    |
| 5007 | Compile Family Digest     | composite |
| 5008 | Detect Mosaic Risk        | composite |
| 5009 | Generate Teachable Moment | composite |
| 5010 | Quarantine High Risk      | composite |
| 5011 | Remediate Content         | composite |
| 5012 | Scan Draft                | composite |
| 5013 | Update Exposure Profile   | composite |

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)
- Python 3.12 (if running services locally without Docker)
- A `.env` file in the project root with the following variables:

```env
DB_SERVER=<azure-sql-server>
DB_NAME=<database-name>
DB_USER=<db-username>
DB_PASSWORD=<db-password>
OPENAI_API_KEY=<your-openai-api-key>
```

### ODBC Driver 18 for SQL Server

Atomic services connect to Azure SQL via ODBC. Install the driver on your machine if running services locally (Docker handles this automatically).

**macOS**

```bash
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew update
brew install microsoft/mssql-release/msodbcsql18
```

**Windows**

Download and run the installer from Microsoft:
[https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server](https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server)

Select **ODBC Driver 18 for SQL Server** for your Windows architecture (x64 recommended).

---

## Running the Program

### With Docker (recommended)

Build and start all services:

```bash
cd backend
docker compose up --build
```

To run in the background:

```bash
cd backend
docker compose up --build -d
```

To stop all services:

```bash
docker compose down
```

### Running a single service locally

```bash
cd backend/atomic/users        # replace with the target service directory
pip install -r requirements.txt
flask run
```

---

## Running Test Scripts

```bash
docker compose -f docker-compose.yml -f docker-compose-dev.yml up --build edits quarantine_items
```

## Accessing Swagger

Once all services are running, open the combined Swagger UI in your browser:

```
http://localhost:5000/docs
```

The docs page aggregates API specs from all services. You can switch between them using the dropdown at the top of the page.

To access an individual service's raw OpenAPI spec:

```
http://localhost:<port>/swagger
```

For example:

- `http://localhost:5001/swagger` — Users
- `http://localhost:5002/swagger` — Content Drafts
