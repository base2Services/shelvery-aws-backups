import pytest


@pytest.fixture(scope="session", autouse=True)
def setup(request):
    """Override the parent conftest setup fixture for unit tests (no AWS needed)."""
    pass
