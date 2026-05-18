"""Shared pytest fixtures."""

import pytest


@pytest.fixture
def example_hello_line() -> str:
    return '{"v":1,"type":"hello","data":{"firmware_version":"0.1.0"}}'
