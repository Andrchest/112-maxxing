"""Repository-root pytest hook shared by every `testpaths` entry (backend, voice agent, benchmarks).

Loaded before any test package's own conftest, so it runs before `app.config.settings` is
imported anywhere: the suites never read a developer's `./.env` (a host run of the demo leaves a
real-provider one at the repo root, which would otherwise flip fake-provider tests — E20).
`make test-backend` sets the same variable explicitly; this covers a bare `uv run pytest`.
"""

import os

os.environ.setdefault("SIM_ENV_FILE", "")
