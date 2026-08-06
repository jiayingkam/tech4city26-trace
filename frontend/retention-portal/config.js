// Backend service base URLs — the one place to edit when pointing this
// static page at a different environment (same "one hardcoded place" idea
// as backend/retention_guard/docs/app.py's Swagger `urls` list). This is a
// plain static file (not a server route) because the portal deploys to
// Vercel as static HTML/JS/CSS with no backend of its own.
//
// Auto-detects local vs. deployed by the page's own hostname, rather than
// requiring this file to be hand-edited before every local test / every
// deploy — that manual toggle is exactly the kind of thing that's easy to
// forget and accidentally ship (e.g. deploying to Vercel while still
// pointed at localhost, or testing locally against live production data).
const isLocal = ["localhost", "127.0.0.1"].includes(window.location.hostname);

window.RG_CONFIG = isLocal
  ? {
      // Matches backend/docker-compose-retention.yml's published ports.
      businessAdminsUrl: "http://localhost:5101",
      dataSourcesUrl: "http://localhost:5102",
      retentionPoliciesUrl: "http://localhost:5103",
      auditLogUrl: "http://localhost:5104",
      enforceRetentionUrl: "http://localhost:5105",
    }
  : {
      businessAdminsUrl: "https://retention-business-admins-658022855661.asia-southeast1.run.app",
      dataSourcesUrl: "https://retention-data-sources-658022855661.asia-southeast1.run.app",
      retentionPoliciesUrl: "https://retention-retention-policies-658022855661.asia-southeast1.run.app",
      auditLogUrl: "https://retention-audit-log-658022855661.asia-southeast1.run.app",
      enforceRetentionUrl: "https://retention-enforce-retention-658022855661.asia-southeast1.run.app",
    };
