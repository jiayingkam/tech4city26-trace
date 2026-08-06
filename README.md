# Tech4City 2026 — Trace

A microservices backend built with Flask, organised into **atomic** (CRUD) and **composite** (orchestration) services.

**Introduction Video:**

[youtu.be/1gd-T9Ew_XI?si=yYajSDrcUiiEqpU9](https://youtu.be/1gd-T9Ew_XI?si=yYajSDrcUiiEqpU9)

---

## 1. Service Port Mappings

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
| 5016 | Scan Video                | composite |
| 5017 | Teachable Moment Chat     | composite |

These ports are only for local Docker Compose. In production each service is deployed separately on Google Cloud Run, so the frontend is instead pointed at whatever URL each one gets there (see "Running the Frontend" below).

---

## 2. Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)
- Python 3.12 (if running services locally without Docker)
- [Node.js](https://nodejs.org/) `^20.19.0` or `>=22.12.0` (only needed to run the frontend — see below)
- A GCP service-account key with Cloud Storage access, saved under `secret/` — also used by `scan_video` to call the Video Intelligence API (see the `CLOUD_VIDEO_INTELLIGENCE_KEY` note below for why a service account is required there instead of a plain API key).
- A `.env` file in the project root with the following variables. `DB_SERVER`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` can be left blank unless you're using the optional real-Azure flow below — the local dev stack overrides them with its own local SQL Server credentials:

```env
DB_SERVER=<azure-sql-server>
DB_NAME=<database-name>
DB_USER=<db-username>
DB_PASSWORD=<db-password>
OPENAI_API_KEY=<your-openai-api-key>
CLOUD_VISION_KEY=<your-google-cloud-vision-api-key>
CLOUD_VIDEO_INTELLIGENCE_KEY=<your-google-cloud-video-intelligence-api-key>  # provisioned but NOT used — see note below
FRONTEND_ORIGIN=<comma-separated allowed CORS origins, e.g. https://your-frontend.vercel.app>
JWT_SECRET_KEY=<secret used to sign/verify login tokens>
INTERNAL_API_KEY=<shared secret for service-to-service calls under /internal/>
GCS_BUCKET=<google-cloud-storage-bucket-name>
```

> **`CLOUD_VIDEO_INTELLIGENCE_KEY` is not actually used anywhere** — confirmed against the real API while building video scanning support: Video Intelligence's `videos:annotate` method rejects plain API-key auth outright (`401 UNAUTHENTICATED`, both over gRPC and REST), unlike Cloud Vision, which does accept one (see `CLOUD_VISION_KEY` above). `scan_video` instead authenticates with the GCP service-account key already used for Cloud Storage (`GOOGLE_APPLICATION_CREDENTIALS`, see Prerequisites above), which does have permission to call it. The env var is left in `.env`/here only because it's already provisioned; it isn't read by any service.

## 3. Running the Program Locally

### With Docker (recommended)

Build and start the whole backend against a local SQL Server container — no Azure connection, no compute cost:

```bash
cd backend
docker compose -f docker-compose.yml -f docker-compose-dev.yml up --build
```

This brings up a `local_db` container plus every atomic and composite service, wired to talk to `local_db` instead of `azure_db`. The `trace_dev` database and its tables are created automatically on every boot — no manual `init-db` step needed (see "Recreating the database" below). Data persists across restarts in the `local_db_data` volume.

To stop:

```bash
docker compose -f docker-compose.yml -f docker-compose-dev.yml down
```

For a clean slate (also wipes the local database):

```bash
docker compose -f docker-compose.yml -f docker-compose-dev.yml down -v
```

Then, start your frontend in a separate terminal:

```bash
cd frontend
npm install
npm run dev
```

### Running against the real Azure DB (optional)

Only needed when you specifically want to validate against production infra — e.g. before a release, or to confirm the Azure path itself still works. Requires the real `DB_SERVER`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` values in `.env`.

```bash
cd backend
docker compose up --build
```

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

**In the local dev stack**, this already runs automatically as part of each service's startup command (see `docker-compose-dev.yml`) — new tables just appear the next time you `docker compose -f docker-compose.yml -f docker-compose-dev.yml up`, nothing to run yourself.

**Against the real Azure DB**, it does **not** run automatically — it used to run on every cold start, but that meant paying for a DB wake-up and a full schema check on every boot, so it was pulled out into a one-off manual command there.

**Run it manually (Azure only) whenever:**

- You're setting up the Azure SQL database for the first time.
- You've added a new model, or a new table, to any atomic service.

**It will NOT:**

- Alter existing tables (add/remove/rename columns, change types, etc.) — `db.create_all()` only creates tables that don't exist yet. If you change an existing model's columns, you need to alter the table yourself (e.g. via a manual `ALTER TABLE`, or by dropping and recreating the table if the data is disposable).

  This applies to video scanning support: `detections.time_range` and `content_drafts.scan_status`/`scan_operation` are new columns on tables that already existed. If your `local_db` was already running before pulling this change, either wipe it (`docker compose -f docker-compose.yml -f docker-compose-dev.yml down -v`, then `up --build` again — data is disposable there) or run the three `ALTER TABLE` statements yourself if you have data worth keeping. Against Azure, run `ALTER TABLE` manually — `init-db` won't add them.

**How to run it**, per service, with the Azure-backed containers already up:

```bash
cd backend
docker compose exec users flask --app app.app:create_app init-db
docker compose exec content_drafts flask --app app.app:create_app init-db
docker compose exec detections flask --app app.app:create_app init-db
docker compose exec edits flask --app app.app:create_app init-db
docker compose exec exposure_profiles flask --app app.app:create_app init-db
docker compose exec quarantine_items flask --app app.app:create_app init-db
```

Only re-run it for the service(s) whose **models changed** — it's harmless to run against a service with no new tables, it just no-ops.

## Running the Frontend Locally

```bash
cd frontend
npm install
npm run dev
```

Opens at `http://localhost:3000`. The upload/scan/remediation flow calls `upload_post` (5014), `scan_draft` (5012), `detections` (5003), `remediate_content` (5011), `quarantine_high_risk` (5010), `generate_teachable_moment` (5009), `teachable_moment_chat` (5017), and `manage_history` (5015) directly from the browser — CORS is already enabled on each. For a video draft, `scan_draft` proxies the actual video scan to `scan_video` (5016) itself; the frontend never calls `scan_video` directly, it just keeps polling `scan_draft`'s `/process` endpoint the same way it does for images.

---

## Running Test Scripts

### Unit tests (mocked database)

Runs each service's route tests with the database mocked out — fast, but never touches a real service or a real DB.

```bash
docker compose -f docker-compose.yml -f docker-compose-test.yml up --build edits quarantine_items
```

### End-to-end smoke test

Exercises the real running stack over HTTP — no mocks. Walks through the actual pipeline: a draft is created, `scan_draft` scans it for real (text via LLM, image via EXIF + LLM), and depending on what's found it's routed to `remediate_content` (propose → confirm → download → revert) or `quarantine_high_risk` (hold → cooldown). Covers Feature 1 (Pre-Post Scan) and Feature 2 (One-Tap Remediation & Quarantine).

Needs a running DB (local or Azure) and working `OPENAI_API_KEY`/`CLOUD_VISION_KEY` values in `.env` — the LLM/vision calls are real and billed regardless of which DB you point at, so it's not free and not instant.

This script predates `upload_post` and creates drafts by writing directly into the shared storage volume rather than through the real HTTP upload path — it does not exercise `upload_post` itself. To test the actual upload flow the frontend uses, run the frontend against the live stack instead (see "Running the Frontend" above).

**Against the local dev stack (recommended for routine runs — no Azure compute cost):**

```bash
cd backend

# 1. Bring up the dev stack (local SQL Server, not Azure)
docker compose -f docker-compose.yml -f docker-compose-dev.yml up --build -d content_drafts detections edits \
  quarantine_items scan_draft scan_video remediate_content quarantine_high_risk

# 2. Build and run the smoke test as a standalone container on the same network
docker build -t backend-smoke_test ./testing/smoke
docker run --rm --network backend_default -v backend_draft_storage:/service/storage backend-smoke_test

# 3. Tear down when done
docker compose -f docker-compose.yml -f docker-compose-dev.yml down
```

**Against the real Azure DB** (only when you specifically need to validate against production infra):

```bash
cd backend

# 1. Bring up the real stack (base compose file only — do NOT add
#    docker-compose-test.yml here, it overrides edits/quarantine_items to run
#    pytest instead of their real server, which breaks everything downstream)
docker compose -f docker-compose.yml up --build -d azure_db content_drafts detections edits \
  quarantine_items scan_draft scan_video remediate_content quarantine_high_risk

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

---

## Retention Guard — standalone PDPA data-retention API

A second, separate product living in this repo (`backend/retention_guard/`) — not part of TRACE's teen-safety scanner. A business registers a connection to their own SQL database, classifies which columns hold PII, defines retention rules ("anonymise customers inactive >180 days"), and this API scans/enforces those rules on a schedule, keeping a full audit trail as compliance evidence. See `.claude/plans` (or ask whoever built it) for the full design writeup — this section is just enough to run it.

It has its own admin accounts (`business_admins`, unrelated to TRACE's `users`), its own Postgres metadata DB, and its own Swagger docs aggregator — brought up entirely independently of the rest of TRACE.

### Port mappings

| Port | Service              | Type      |
| ---- | -------------------- | --------- |
| 5100 | Retention Guard Docs | docs      |
| 5101 | Business Admins      | atomic    |
| 5102 | Data Sources         | atomic    |
| 5103 | Retention Policies   | atomic    |
| 5104 | Audit Log            | atomic    |
| 5105 | Enforce Retention    | composite |

### Extra prerequisite

Add one more variable to the root `.env` (alongside `JWT_SECRET_KEY`/`INTERNAL_API_KEY`, which this product reuses as-is):

```env
CONN_STRING_ENCRYPTION_KEY=<Fernet key — generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
```

This encrypts registered data sources' connection strings at rest (`shared/trace_crypto`) — only the `data_sources` service ever decrypts them.

### Running it

```bash
cd backend
docker compose -f docker-compose-retention.yml up --build
```

This brings up its own `retention_guard_db` Postgres container plus all five services, wired together — no dependency on TRACE's own `azure_db`/`local_db` or any other TRACE service. Tables are created automatically on every boot (`db.create_all()` is idempotent against Postgres, so unlike TRACE's own Azure-backed `init-db` step, there's nothing manual to run here). Data persists across restarts in the `retention_guard_db_data` volume.

```bash
docker compose -f docker-compose-retention.yml down        # stop
docker compose -f docker-compose-retention.yml down -v      # stop + wipe data
```

Open the combined Swagger UI at `http://localhost:5100/docs` and walk through: **signup → login → register your fake company's data source (its own connection string, not TRACE's DB) → classify its PII/subject-id/activity-timestamp columns → create a retention policy → dry-run scan → review matches in the audit log → approve → enforce → confirm the rows were actually anonymised/deleted on the source.**

Note: the data source you register must be a database this compose network (or, once deployed, Cloud Run) can actually reach — a Postgres instance only listening on `localhost` outside this compose network won't work. For local dev, add it as another service on the same Docker network; once deployed, it needs a real public/reachable endpoint (a small hosted Postgres — Cloud SQL, Supabase, Neon, etc.).

### Deploying

Same manual, one-service-at-a-time Cloud Run deploy as the rest of TRACE (see "Service Port Mappings" note above) — each of the 5 services gets its own public HTTPS URL. Set `CONN_STRING_ENCRYPTION_KEY` alongside `JWT_SECRET_KEY`/`INTERNAL_API_KEY` in each service's Cloud Run environment/secrets.

### Running its tests

```bash
pip install -r backend/retention_guard/atomic/business_admins/requirements-dev.txt  # pytest + cryptography, shared by all five services
python -m pytest backend/testing/atomic/business_admins backend/testing/atomic/data_sources \
  backend/testing/atomic/retention_policies backend/testing/atomic/audit_log \
  backend/testing/composite/enforce_retention
```

Run from the **repo root**, not via Docker — every test file imports its service under a fully-qualified path (`from backend.retention_guard.atomic.business_admins.app.routes import ...`), which only resolves when the repo root itself is on `sys.path`. TRACE's own `docker-compose.yml`/`docker-compose-test.yml` route (see "Unit tests (mocked database)" above) doesn't actually give you that: each service's container only ever has its own flattened `/service/app` — there's no `backend/` tree inside it for that import to resolve against, confirmed while building this feature. That's a pre-existing gap in the Docker test runner, not something introduced here, and it's why retention_guard's tests are documented to run locally instead rather than copying that pattern into more services.

`retention_engine.py`'s tests (the query-builder/whitelist logic — the highest-value target) need no DB or service running at all — they exercise a real file-backed SQLite engine directly.
