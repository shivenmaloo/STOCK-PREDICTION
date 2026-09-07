from unittest.mock import MagicMock, patch

import requests as requests_module


def test_chat_refuses_gracefully_without_api_key():
    from backend.config import settings
    import backend.chat.service as chat_service

    original = settings.ANTHROPIC_API_KEY
    settings.ANTHROPIC_API_KEY = ""
    try:
        result = chat_service.send_chat_message([{"role": "user", "content": "hello"}])
        assert result["success"] is False
        assert "ANTHROPIC_API_KEY" in result["error"]
        assert chat_service.is_configured() is False
    finally:
        settings.ANTHROPIC_API_KEY = original


def test_chat_returns_reply_on_success():
    from backend.config import settings
    import backend.chat.service as chat_service

    original = settings.ANTHROPIC_API_KEY
    settings.ANTHROPIC_API_KEY = "fake-key"
    try:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Here's the answer."}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        with patch("backend.chat.service.requests.post", return_value=mock_response):
            result = chat_service.send_chat_message([{"role": "user", "content": "test"}])
        assert result["success"] is True
        assert result["reply"] == "Here's the answer."
    finally:
        settings.ANTHROPIC_API_KEY = original


def test_chat_includes_context_when_provided():
    from backend.config import settings
    import backend.chat.service as chat_service

    original = settings.ANTHROPIC_API_KEY
    settings.ANTHROPIC_API_KEY = "fake-key"
    try:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": [{"type": "text", "text": "ok"}]}
        with patch("backend.chat.service.requests.post", return_value=mock_response) as mock_post:
            chat_service.send_chat_message(
                [{"role": "user", "content": "why?"}],
                context={"ticker": "NVDA", "signal": "NEUTRAL"},
            )
        sent = mock_post.call_args.kwargs["json"]["messages"]
        assert "NVDA" in sent[0]["content"]
    finally:
        settings.ANTHROPIC_API_KEY = original


def test_chat_handles_api_error_response():
    from backend.config import settings
    import backend.chat.service as chat_service

    original = settings.ANTHROPIC_API_KEY
    settings.ANTHROPIC_API_KEY = "fake-key"
    try:
        error_response = MagicMock()
        error_response.status_code = 401
        error_response.text = "Invalid API key"
        with patch("backend.chat.service.requests.post", return_value=error_response):
            result = chat_service.send_chat_message([{"role": "user", "content": "hi"}])
        assert result["success"] is False
        assert "401" in result["error"]
    finally:
        settings.ANTHROPIC_API_KEY = original


def test_chat_handles_network_failure():
    from backend.config import settings
    import backend.chat.service as chat_service

    original = settings.ANTHROPIC_API_KEY
    settings.ANTHROPIC_API_KEY = "fake-key"
    try:
        with patch("backend.chat.service.requests.post", side_effect=requests_module.exceptions.ConnectionError("down")):
            result = chat_service.send_chat_message([{"role": "user", "content": "hi"}])
        assert result["success"] is False
    finally:
        settings.ANTHROPIC_API_KEY = original


def test_chat_rejects_empty_message_list():
    from backend.config import settings
    import backend.chat.service as chat_service

    original = settings.ANTHROPIC_API_KEY
    settings.ANTHROPIC_API_KEY = "fake-key"
    try:
        result = chat_service.send_chat_message([])
        assert result["success"] is False
    finally:
        settings.ANTHROPIC_API_KEY = original


def test_chat_trims_long_history():
    from backend.config import settings
    import backend.chat.service as chat_service

    original = settings.ANTHROPIC_API_KEY
    settings.ANTHROPIC_API_KEY = "fake-key"
    try:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"content": [{"type": "text", "text": "ok"}]}
        long_history = [{"role": "user", "content": f"msg {i}"} for i in range(50)]
        with patch("backend.chat.service.requests.post", return_value=mock_response) as mock_post:
            chat_service.send_chat_message(long_history)
        sent = mock_post.call_args.kwargs["json"]["messages"]
        assert len(sent) <= chat_service.MAX_HISTORY_MESSAGES
    finally:
        settings.ANTHROPIC_API_KEY = original
