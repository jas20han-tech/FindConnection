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
os.environ.setdefault("GRAPH_ACCUMULATE", "true")
os.environ.setdefault("UPLOAD_DIR", tempfile.mkdtemp(prefix="graphrag-tests-uploads-"))
os.environ.setdefault("NETWORK_DIR", tempfile.mkdtemp(prefix="graphrag-tests-networks-"))

# Tests must stay offline and deterministic even when the developer's .env has
# real provider keys. Blank keys win over .env because env vars take precedence.
os.environ["GEMINI_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["OLLAMA_ENABLED"] = "false"
