import json
from types import SimpleNamespace

import httpx
import pytest

import fetch


class FakeResponse:
    """Stands in for the object httpx.stream() hands back."""

    def __init__(self, status_code, lines=()):
        self.status_code = status_code
        self._lines = list(lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def iter_lines(self):
        return iter(self._lines)

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://lichess.org")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)


def game_line(game_id="abc", created_at=1000):
    return json.dumps({"id": game_id, "createdAt": created_at})


@pytest.fixture
def fake_lichess(monkeypatch):
    """Queue fake responses; inspect the requests made and the sleeps requested."""
    fake = SimpleNamespace(queue=[], calls=[], sleeps=[])

    def fake_stream(method, url, **kwargs):
        fake.calls.append({"url": url, **kwargs})
        return fake.queue.pop(0)

    monkeypatch.setattr(fetch.httpx, "stream", fake_stream)
    monkeypatch.setattr(fetch.time, "sleep", fake.sleeps.append)
    return fake


def test_yields_one_dict_per_line_and_skips_blank_lines(fake_lichess):
    fake_lichess.queue.append(FakeResponse(200, [game_line("a"), "", game_line("b")]))

    games = list(fetch.stream_games("blazene"))

    assert [g["id"] for g in games] == ["a", "b"]


def test_sends_user_agent_and_accept_headers(fake_lichess):
    fake_lichess.queue.append(FakeResponse(200))

    list(fetch.stream_games("blazene"))

    headers = fake_lichess.calls[0]["headers"]
    assert "chess-analyzer" in headers["User-Agent"]
    assert headers["Accept"] == "application/x-ndjson"


def test_since_is_sent_as_a_parameter(fake_lichess):
    fake_lichess.queue.append(FakeResponse(200))

    list(fetch.stream_games("blazene", since_ms=1000))

    assert fake_lichess.calls[0]["params"]["since"] == 1000


def test_no_since_parameter_by_default(fake_lichess):
    fake_lichess.queue.append(FakeResponse(200))

    list(fetch.stream_games("blazene"))

    assert "since" not in fake_lichess.calls[0]["params"]


def test_games_older_than_since_are_dropped(fake_lichess):
    lines = [game_line("old", 500), game_line("new", 1500)]
    fake_lichess.queue.append(FakeResponse(200, lines))

    games = list(fetch.stream_games("blazene", since_ms=1000))

    assert [g["id"] for g in games] == ["new"]


def test_retries_after_429(fake_lichess):
    fake_lichess.queue.append(FakeResponse(429))
    fake_lichess.queue.append(FakeResponse(200, [game_line("a")]))

    games = list(fetch.stream_games("blazene"))

    assert [g["id"] for g in games] == ["a"]
    assert fake_lichess.sleeps == [fetch.RATE_LIMIT_WAIT_SECONDS]
    assert len(fake_lichess.calls) == 2


def test_gives_up_after_max_attempts(fake_lichess):
    for _ in range(fetch.MAX_ATTEMPTS):
        fake_lichess.queue.append(FakeResponse(429))

    with pytest.raises(RuntimeError, match="rate limited"):
        list(fetch.stream_games("blazene"))

    assert len(fake_lichess.sleeps) == fetch.MAX_ATTEMPTS - 1


def test_404_gives_a_helpful_error(fake_lichess):
    fake_lichess.queue.append(FakeResponse(404))

    with pytest.raises(RuntimeError, match="User-Agent"):
        list(fetch.stream_games("blazene"))


def test_other_http_errors_propagate(fake_lichess):
    fake_lichess.queue.append(FakeResponse(500))

    with pytest.raises(httpx.HTTPStatusError):
        list(fetch.stream_games("blazene"))
