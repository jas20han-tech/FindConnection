"""Test bootstrap: force a clean, dependency-free runtime.

The in-memory repository persists ingested documents to disk so a restart does not
drop them, and uploads are written to ``backend/uploads`` at runtime. Tests must never
read, overwrite or pollute either location.
"""

import os
import tempfile

os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("USE_CELERY", "false")
os.environ.setdefault("GRAPH_PERSIST", "false")
os.environ.setdefault("UPLOAD_DIR", tempfile.mkdtemp(prefix="graphrag-tests-uploads-"))
