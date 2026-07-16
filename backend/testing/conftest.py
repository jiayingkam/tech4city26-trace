import os
import sys

# Composite services import `trace_auth` as a bare top-level package — inside
# each container it's copied to sit right next to `app/` (see the
# Dockerfiles' `COPY shared/trace_auth trace_auth/`), so that import only
# resolves here too if `shared/` is on sys.path the same way. `shared/` is a
# sibling of this file's parent (`backend/shared`, next to `backend/testing`),
# not a child of it — this file lives one level deeper than the old
# `backend/conftest.py` did, so it has to walk up one more directory first.
backend_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(backend_dir, "shared"))
