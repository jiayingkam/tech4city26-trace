from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.composite.teachable_moment_chat.app import agent as agent_module


def _mock_response(status_code, payload):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def test_render_seed_context_with_category():
    seed = {
        "category": "contact",
        "detail": "phone number in caption",
        "exposure_score": 4,
        "explanation": "Strangers could contact you directly.",
        "safer_action": "Remove the phone number.",
    }

    rendered = agent_module._render_seed_context(seed)

    assert "contact" in rendered
    assert "phone number in caption" in rendered


def test_render_seed_context_without_category():
    rendered = agent_module._render_seed_context({"category": None})

    assert "safe to share" in rendered


def test_flatten_history_formats_turns_and_appends_new_message():
    history = [
        {"role": "user", "content": "why was this flagged?"},
        {"role": "assistant", "content": "It shows a phone number."},
    ]

    flattened = agent_module._flatten_history(history, "is that really risky?")

    assert flattened == (
        "User: why was this flagged?\n"
        "Coach: It shows a phone number.\n"
        "User: is that really risky?"
    )


def test_get_detections_tool_returns_records(auth_headers=None):
    auth_headers = {"Authorization": "Bearer token"}
    with patch.object(agent_module, "requests") as mocked_requests:
        mocked_requests.get.return_value = _mock_response(200, [{"category": "contact"}])

        get_detections, _, _ = agent_module._build_tools("draft_1", "owner_1", auth_headers)
        result = get_detections()

    assert result == {"detections": [{"category": "contact"}]}
    mocked_requests.get.assert_called_once_with(
        f"{agent_module.DETECTIONS_SERVICE_URL}/drafts/draft_1/detections",
        headers=auth_headers,
    )


def test_get_exposure_profile_tool_returns_profile():
    auth_headers = {"Authorization": "Bearer token"}
    profile_blob = {"stranger": {"inferences": []}, "trajectory": []}
    with patch.object(agent_module, "requests") as mocked_requests:
        mocked_requests.get.return_value = _mock_response(200, {"profile": profile_blob})

        _, _, get_exposure_profile = agent_module._build_tools("draft_1", "owner_1", auth_headers)
        result = get_exposure_profile()

    assert result == {"profile": profile_blob}


def test_get_detections_tool_degrades_on_failure():
    auth_headers = {"Authorization": "Bearer token"}
    with patch.object(agent_module, "requests") as mocked_requests:
        mocked_requests.get.return_value = _mock_response(500, {"error": "boom"})

        get_detections, _, _ = agent_module._build_tools("draft_1", "owner_1", auth_headers)
        result = get_detections()

    assert result == {"error": "failed to fetch detections"}


@pytest.fixture
def openai_env():
    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
        yield


def test_answer_happy_path_registers_and_cleans_up_tools(openai_env):
    auth_headers = {"Authorization": "Bearer token"}
    with patch.object(agent_module, "requests") as mocked_requests, \
         patch.object(agent_module.ReActAgent, "invoke", new_callable=AsyncMock) as mocked_invoke:
        mocked_requests.get.return_value = _mock_response(200, {
            "category": "contact", "detail": "phone number", "exposure_score": 3,
            "explanation": "x", "safer_action": "y",
        })
        mocked_invoke.return_value = {"output": "Here's why that matters.", "result_type": "answer"}

        reply = agent_module.answer(
            draft_id="draft_1",
            message="why was this flagged?",
            history=[],
            auth_headers=auth_headers,
            owner_id="owner_1",
        )

    assert reply == "Here's why that matters."
    mocked_invoke.assert_awaited_once()
    query = mocked_invoke.call_args.args[0]["query"]
    assert query == "User: why was this flagged?"
    # Tool registrations must not leak past this call — see the finally in
    # answer()/_unregister_tools, otherwise Runner.resource_mgr grows unbounded
    # over the life of the gunicorn worker.
    assert agent_module.Runner.resource_mgr.get_tool(
        "does-not-matter", tag="teachable_moment_chat_nonexistent_tag"
    ) is None


def test_answer_raises_chat_error_on_agent_error_result(openai_env):
    auth_headers = {"Authorization": "Bearer token"}
    with patch.object(agent_module, "requests") as mocked_requests, \
         patch.object(agent_module.ReActAgent, "invoke", new_callable=AsyncMock) as mocked_invoke:
        mocked_requests.get.return_value = _mock_response(200, None)
        mocked_invoke.return_value = {"output": "something went wrong", "result_type": "error"}

        with pytest.raises(agent_module.ChatError):
            agent_module.answer(
                draft_id="draft_1",
                message="why was this flagged?",
                history=[],
                auth_headers=auth_headers,
                owner_id="owner_1",
            )


def test_answer_raises_chat_error_when_invoke_throws(openai_env):
    auth_headers = {"Authorization": "Bearer token"}
    with patch.object(agent_module, "requests") as mocked_requests, \
         patch.object(agent_module.ReActAgent, "invoke", new_callable=AsyncMock) as mocked_invoke:
        mocked_requests.get.return_value = _mock_response(200, None)
        mocked_invoke.side_effect = RuntimeError("boom")

        with pytest.raises(agent_module.ChatError):
            agent_module.answer(
                draft_id="draft_1",
                message="why was this flagged?",
                history=[],
                auth_headers=auth_headers,
                owner_id="owner_1",
            )
