from app.core.config import Settings


def test_settings_default_to_sqlite_when_database_is_unset(monkeypatch) -> None:
    for env_name in ("DATABASE_URL", "DATABASE_URL_UNPOOLED", "SQLALCHEMY_DATABASE_URI", "LOCAL_DB_MODE"):
        monkeypatch.delenv(env_name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.LOCAL_DB_MODE == "sqlite"
    assert settings.DATABASE_URL is None
    assert settings.DATABASE_URL_UNPOOLED is None
    assert settings.SQLALCHEMY_DATABASE_URI == "sqlite:///./healthsynch.db"


def test_neon_mode_uses_explicit_database_url() -> None:
    database_url = "postgresql://user:password@example.com/healthsynch?sslmode=require"

    settings = Settings(
        _env_file=None,
        LOCAL_DB_MODE="neon",
        DATABASE_URL=database_url,
    )

    assert settings.DATABASE_URL == database_url
    assert settings.SQLALCHEMY_DATABASE_URI == database_url


def test_placeholder_database_url_is_not_promoted_to_runtime_default() -> None:
    settings = Settings(
        _env_file=None,
        LOCAL_DB_MODE="neon",
        DATABASE_URL=(
            "postgresql://username:password@ep-xxxxx.region.aws.neon.tech/"
            "neondb?channel_binding=require&sslmode=require"
        ),
    )

    assert settings.DATABASE_URL is None
    assert settings.SQLALCHEMY_DATABASE_URI == "sqlite:///./healthsynch.db"


def test_admin_bootstrap_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ADMIN_BOOTSTRAP_ENABLED", raising=False)
    monkeypatch.delenv("ADMIN_BOOTSTRAP_PASSWORD", raising=False)

    settings = Settings(_env_file=None)

    assert settings.ADMIN_BOOTSTRAP_ENABLED is False
    assert settings.ADMIN_BOOTSTRAP_PASSWORD is None
