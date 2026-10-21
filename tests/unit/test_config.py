from app.config import Settings


def test_default_settings():
    settings = Settings()

    assert settings.app_name == "Customer Support Resolution Agent"
    assert settings.environment == "development"