import pytest

from app import serve


def test_server_defaults_bind_locally_in_development() -> None:
    settings = serve.ServerSettings.from_environment(
        {"STUDYROOM_ENV": "development"}
    )

    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.workers == 1
    assert settings.reload is False
    assert settings.access_log is True


def test_server_defaults_to_provider_binding_in_production() -> None:
    settings = serve.ServerSettings.from_environment(
        {"STUDYROOM_ENV": "production", "PORT": "4310"}
    )

    assert settings.host == "0.0.0.0"
    assert settings.port == 4310
    assert settings.access_log is False


@pytest.mark.parametrize("port", ("0", "65536", "not-a-port"))
def test_server_rejects_invalid_provider_ports(port: str) -> None:
    with pytest.raises(serve.ServerConfigurationError):
        serve.ServerSettings.from_environment({"PORT": port})


def test_server_rejects_unknown_runtime_environment() -> None:
    with pytest.raises(serve.ServerConfigurationError):
        serve.ServerSettings.from_environment({"STUDYROOM_ENV": "staging"})


def test_launch_contract_is_one_process_without_reload_or_forwarded_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(application: str, **kwargs: object) -> None:
        calls.append({"application": application, **kwargs})

    monkeypatch.setenv("STUDYROOM_ENV", "production")
    monkeypatch.setenv("PORT", "4321")
    monkeypatch.setattr(serve.uvicorn, "run", fake_run)

    serve.main()

    assert calls == [
        {
            "application": "app.main:app",
            "host": "0.0.0.0",
            "port": 4321,
            "workers": 1,
            "reload": False,
            "proxy_headers": False,
            "access_log": False,
        }
    ]
