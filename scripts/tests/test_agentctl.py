import pytest

from agentctl import SlugError, validate_slug


@pytest.mark.parametrize(
    "slug",
    [
        "agent-edgar",
        "agent-chaos",
        "agent-a1",
        "agent-z9-test",
        "agent-" + "x" * 25,
    ],
)
def test_valid_slugs(slug):
    validate_slug(slug)


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "edgar",
        "agent-",
        "agent-Edgar",
        "agent--edgar",
        "agent-edgar-",
        "agent-" + "x" * 30,
        "agent-edgar/etc/passwd",
    ],
)
def test_invalid_slugs(slug):
    with pytest.raises(SlugError):
        validate_slug(slug)
