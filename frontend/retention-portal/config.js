// Backend service base URLs — the one place to edit when pointing this
// static page at a different environment (same "one hardcoded place" idea
// as backend/retention_guard/docs/app.py's Swagger `urls` list). This is a
// plain static file (not a server route) because the portal deploys to
// Vercel as static HTML/JS/CSS with no backend of its own — edit this file
// and redeploy when the backend URLs change.
//
// Set to the live deployed Cloud Run URLs, same as backend/retention_guard/
// docs/app.py's own hardcoded `urls` list. For local dev against
// `docker compose -f backend/docker-compose-retention.yml up`, swap these
// for http://localhost:5101-5105 instead.
window.RG_CONFIG = {
  businessAdminsUrl: "https://retention-business-admins-658022855661.asia-southeast1.run.app",
  dataSourcesUrl: "https://retention-data-sources-658022855661.asia-southeast1.run.app",
  retentionPoliciesUrl: "https://retention-retention-policies-658022855661.asia-southeast1.run.app",
  auditLogUrl: "https://retention-audit-log-658022855661.asia-southeast1.run.app",
  enforceRetentionUrl: "https://retention-enforce-retention-658022855661.asia-southeast1.run.app",
};
