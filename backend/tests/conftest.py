"""Test setup: local fake user, mock agent."""

import os

os.environ.setdefault("DEV_AUTH", "1")
os.environ.setdefault("AGENT_MODE", "mock")
