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
| 5014 | Upload Post               | composite |

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)
- Python 3.12 (if running services locally without Docker)
- [Node.js](https://nodejs.org/) `^20.19.0` or `>=22.12.0` (only needed to run the frontend — see below)
- A `.env` file in the project root with the following variables:

```env
DB_SERVER=<azure-sql-server>
DB_NAME=<database-name>
DB_USER=<db-username>
DB_PASSWORD=<db-password>
OPENAI_API_KEY=<your-openai-api-key>
CLOUD_VISION_KEY=<your-google-cloud-vision-api-key>
CLOUD_VIDEO_INTELLIGENCE_KEY=<your-google-cloud-video-intelligence-api-key>
```

`CLOUD_VISION_KEY` is a plain Google Cloud API key (Cloud Vision API enabled on the project) — used by `scan_draft` for OCR text/location detection in photos.

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

## Running the Frontend

The Vue app is what actually drives Feature 1 (Pre-Post Scan) and Feature 2 (One-Tap Remediation & Quarantine) — the backend alone has no UI beyond Swagger. It needs the backend stack running (see above) at the same time, since it calls the composite services directly over HTTP.

```bash
cd frontend
npm install
npm run dev
```

Opens at `http://localhost:3000`. The upload/scan/remediation flow calls `upload_post` (5014), `scan_draft` (5012), `detections` (5003), `remediate_content` (5011), and `quarantine_high_risk` (5010) directly from the browser — CORS is already enabled on each.

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
