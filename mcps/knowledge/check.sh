#!/bin/sh
set -eu

KNOWLEDGE_PYTHON="${KNOWLEDGE_PYTHON:-python}"

"$KNOWLEDGE_PYTHON" -m ruff check src tests
"$KNOWLEDGE_PYTHON" -m ruff format --check src tests
"$KNOWLEDGE_PYTHON" -m compileall -q src tests
PYTHONPATH=src "$KNOWLEDGE_PYTHON" -m unittest discover -s tests -v
