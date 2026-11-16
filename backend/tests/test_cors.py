import pytest

from main import get_cors_allowed_origins


@pytest.mark.parametrize("configured", [None, "", " ,  , "])
def test_cors_origins_default_to_local_frontend(monkeypatch, configured):
    if configured is None:
        monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", configured)

    assert get_cors_allowed_origins() == ["http://localhost:3000"]


def test_cors_origins_are_trimmed_and_empty_entries_ignored(monkeypatch):
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        " https://smartstore.example , , https://another.example  ",
    )

    assert get_cors_allowed_origins() == [
        "https://smartstore.example",
        "https://another.example",
    ]


def test_cors_rejects_wildcard_origin_with_credentials(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://smartstore.example, *")

    with pytest.raises(ValueError, match=r"cannot contain '\*'"):
        get_cors_allowed_origins()
