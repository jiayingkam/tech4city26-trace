# Tech4City 2026 — Trace

A microservices backend built with Flask, organised into **atomic** (CRUD) and **composite** (orchestration) services.

---

## Service Port Mappings

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
| 5014 | Upload Post               | composite |
| 5015 | Manage History            | composite |

These ports are only for local Docker Compose. In production each service is deployed separately on Google Cloud Run, so the frontend is instead pointed at whatever URL each one gets there (see "Running the Frontend" below).

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)
- Python 3.12 (if running services locally without Docker)
- [Node.js](https://nodejs.org/) `^20.19.0` or `>=22.12.0` (only needed to run the frontend — see below)
- A reachable Azure SQL database. The `azure_db` service in `docker-compose.yml` doesn't run a database itself — it's a healthcheck container that logs into the real Azure SQL DB below and gates every other service's startup on that succeeding, so **local Docker Compose still talks to a real remote database**, not a local one.
- A GCP service-account key with Cloud Storage access, saved under `secret/`.
- A `.env` file in the project root with the following variables:

```env
DB_SERVER=<azure-sql-server>
DB_NAME=<database-name>
DB_USER=<db-username>
DB_PASSWORD=<db-password>
OPENAI_API_KEY=<your-openai-api-key>
CLOUD_VISION_KEY=<your-google-cloud-vision-api-key>
CLOUD_VIDEO_INTELLIGENCE_KEY=<your-google-cloud-video-intelligence-api-key>
FRONTEND_ORIGIN=<comma-separated allowed CORS origins, e.g. https://your-frontend.vercel.app>
JWT_SECRET_KEY=<secret used to sign/verify login tokens>
INTERNAL_API_KEY=<shared secret for service-to-service calls under /internal/>
GCS_BUCKET=<google-cloud-storage-bucket-name>
```

## Running the Program Locally

### With Docker (recommended)

Build and start all services:

```bash
cd backend
docker compose up --build
```

To stop all services:

```bash
docker compose down
```

### Recreating the database (`init-db`)

Each atomic service (`users`, `content_drafts`, `detections`, `edits`, `exposure_profiles`, `quarantine_items`) defines its SQLAlchemy models and exposes a Flask CLI command that creates their tables:

```python
# atomic/<service>/app/app.py
@app.cli.command("init-db")
def init_db():
    wait_for_db(db.engine)
    db.create_all()
```

This does **not** run automatically on startup — it used to run on every cold start, but that meant paying for a DB wake-up and a full schema check on every boot, so it was pulled out into a one-off manual command.

**Run it whenever:**

- You're setting up the Azure SQL database for the first time.
- You've added a new model, or a new table, to any atomic service.

**It will NOT:**

- Alter existing tables (add/remove/rename columns, change types, etc.) — `db.create_all()` only creates tables that don't exist yet. If you change an existing model's columns, you need to alter the table yourself (e.g. via a manual `ALTER TABLE`, or by dropping and recreating the table if the data is disposable).

**How to run it**, per service, with the containers already up:

```bash
cd backend
docker compose exec users flask --app app.app:create_app init-db
docker compose exec content_drafts flask --app app.app:create_app init-db
docker compose exec detections flask --app app.app:create_app init-db
docker compose exec edits flask --app app.app:create_app init-db
docker compose exec exposure_profiles flask --app app.app:create_app init-db
docker compose exec quarantine_items flask --app app.app:create_app init-db
```

Only re-run it for the service(s) whose models changed — it's harmless to run against a service with no new tables, it just no-ops.

## Running the Frontend Locally

```bash
cd frontend
npm install
npm run dev
```

Opens at `http://localhost:3000`. The upload/scan/remediation flow calls `upload_post` (5014), `scan_draft` (5012), `detections` (5003), `remediate_content` (5011), `quarantine_high_risk` (5010), `generate_teachable_moment` (5009), and `manage_history` (5015) directly from the browser — CORS is already enabled on each.

---

## Running Test Scripts

### Unit tests (mocked database)

Runs each service's route tests with the database mocked out — fast, but never touches a real service or a real DB.

```bash
docker compose -f docker-compose.yml -f docker-compose-dev.yml up --build edits quarantine_items
```

### End-to-end smoke test

Exercises the real running stack over HTTP — no mocks. Walks through the actual pipeline: a draft is created, `scan_draft` scans it for real (text via LLM, image via EXIF + LLM), and depending on what's found it's routed to `remediate_content` (propose → confirm → download → revert) or `quarantine_high_risk` (hold → cooldown). Covers Feature 1 (Pre-Post Scan) and Feature 2 (One-Tap Remediation & Quarantine).

Needs a reachable Azure SQL DB and working `OPENAI_API_KEY`/`CLOUD_VISION_KEY` values in `.env` — this makes real, billed API calls, so it's not free and not instant.

This script predates `upload_post` and creates drafts by writing directly into the shared storage volume rather than through the real HTTP upload path — it does not exercise `upload_post` itself. To test the actual upload flow the frontend uses, run the frontend against the live stack instead (see "Running the Frontend" above).

```bash
cd backend

# 1. Bring up the real stack (base compose file only — do NOT add
#    docker-compose-dev.yml here, it overrides edits/quarantine_items to run
#    pytest instead of their real server, which breaks everything downstream)
docker compose -f docker-compose.yml up --build -d azure_db content_drafts detections edits \
  quarantine_items scan_draft remediate_content quarantine_high_risk

# 2. Build and run the smoke test as a standalone container on the same network
docker build -t backend-smoke_test ./testing/smoke
docker run --rm --network backend_default -v backend_draft_storage:/service/storage backend-smoke_test

# 3. Tear down when done
docker compose -f docker-compose.yml down
```

Output prints `[ok]` / `[warn]` / `[FAIL]` per step and exits non-zero if anything hard-fails. `[warn]` lines (e.g. the LLM routing to quarantine instead of remediate) aren't failures — those specific branches are LLM-dependent and treated as informational.

## Accessing Swagger

Swagger documents are used to design, build, document, and consume REST APIs. They provide a standardized, machine-readable blueprint that details every endpoint, parameter, and response, allowing developers and automated tools to easily understand and interact with an API.

Once all containers are running, open the combined Swagger UI in your browser:

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
