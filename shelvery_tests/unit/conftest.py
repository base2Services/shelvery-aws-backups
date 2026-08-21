import pytest


@pytest.fixture(scope="session", autouse=True)
def setup(request):
    """Override the parent conftest fixture.

    shelvery_tests/conftest.py stands up a real CloudFormation stack and calls STS at
    collection time. Everything under unit/ runs offline, so that fixture is replaced with
    a no-op here.
    """
    pass
