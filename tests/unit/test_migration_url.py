import pytest

from fateweave.storage.db import select_migration_url

PROD = "postgresql+asyncpg://owner@prod/fateweave"
TEST = "postgresql+asyncpg://postgres@127.0.0.1:55432/scratch"
ATTR = "postgresql+asyncpg://postgres@127.0.0.1:55432/attr"


def test_x_url_wins_over_env_var():
    assert select_migration_url(attribute=None, x_url=TEST, env_url=PROD) == TEST


def test_attribute_wins_over_everything():
    assert select_migration_url(attribute=ATTR, x_url=TEST, env_url=PROD) == ATTR


def test_env_var_is_the_fallback():
    assert select_migration_url(attribute=None, x_url=None, env_url=PROD) == PROD
    assert select_migration_url(attribute="", x_url="", env_url=PROD) == PROD


def test_no_url_raises():
    with pytest.raises(RuntimeError, match="-x url="):
        select_migration_url(attribute=None, x_url=None, env_url=None)
