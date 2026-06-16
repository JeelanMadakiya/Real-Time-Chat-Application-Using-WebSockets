#!/usr/bin/env bash
set -e
source .venv/bin/activate
uvicorn app.main:app --reload
