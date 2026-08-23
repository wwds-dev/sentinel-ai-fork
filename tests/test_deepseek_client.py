import pytest

from services.deepseek_client import (
    DEEPSEEK_BALANCE_MESSAGE,
    DeepSeekClientWrapper,
    DeepSeekInsufficientBalanceError,
)


class _BalanceError(Exception):
    status_code = 402

    def __str__(self):
        return "raw provider payload: Insufficient Balance; secret diagnostic"


class _Completions:
    def create(self, **_kwargs):
        raise _BalanceError()


class _Client:
    class _Chat:
        completions = _Completions()

    chat = _Chat()


def _wrapper_with_failing_client():
    wrapper = DeepSeekClientWrapper.__new__(DeepSeekClientWrapper)
    wrapper.client = _Client()
    return wrapper


def test_chat_turns_http_402_into_non_technical_balance_message():
    with pytest.raises(DeepSeekInsufficientBalanceError) as caught:
        _wrapper_with_failing_client().chat([{"role": "user", "content": "hello"}])

    assert str(caught.value) == DEEPSEEK_BALANCE_MESSAGE
    assert "secret diagnostic" not in str(caught.value)


def test_stream_turns_http_402_into_non_technical_balance_message():
    with pytest.raises(DeepSeekInsufficientBalanceError) as caught:
        list(_wrapper_with_failing_client().stream_chat(
            [{"role": "user", "content": "hello"}]
        ))

    assert str(caught.value) == DEEPSEEK_BALANCE_MESSAGE
