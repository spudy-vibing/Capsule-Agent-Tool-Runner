"""
Pytest configuration and fixtures for Capsule tests.

This module provides shared fixtures used across unit, integration,
and security tests.
"""

import tempfile
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_plan_yaml() -> str:
    """Return a simple plan YAML for testing."""
    return """
version: "1.0"
steps:
  - tool: fs.read
    args:
      path: "./README.md"
"""


@pytest.fixture
def sample_policy_yaml() -> str:
    """Return a simple policy YAML for testing."""
    return """
boundary: deny_by_default
tools:
  fs.read:
    allow_paths:
      - "./**"
    max_size_bytes: 1048576
"""


@pytest.fixture
def strict_policy_yaml() -> str:
    """Return a strict policy YAML that denies most operations."""
    return """
boundary: deny_by_default
tools: {}
"""
