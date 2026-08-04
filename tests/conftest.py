"""Test isolation: unit tests must never appear as production LangSmith traces."""

import os

os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGSMITH_TEST_TRACKING"] = "false"
