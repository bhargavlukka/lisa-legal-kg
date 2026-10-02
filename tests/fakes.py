"""Test doubles for the LLM layer (no network)."""
from lisa.common.config import LLMSettings
from lisa.llm.client import Completion


def llm_settings(**over) -> LLMSettings:
    base = dict(base_url="https://llm.test/openai/v1", model="test-model", api_key="k-test", temperature=0.0,
                max_output_tokens=1000, timeout_s=5.0, max_requests_per_run=100, window_pages=3,
                edge_split_chars=60000, include_unverified_in_graph=False, json_mode=True)
    base.update(over)
    return LLMSettings(**base)


def chat_payload(text: str, finish: str = "stop") -> dict:
    return {"choices": [{"message": {"content": text}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


class FakeClient:
    """Duck-types LLMClient.complete; responder(messages) -> text | (text, finish_reason)."""

    def __init__(self, responder):
        self.responder = responder
        self.calls: list[list[dict]] = []

    def complete(self, messages, prompt_version):
        self.calls.append(messages)
        r = self.responder(messages)
        text, finish = r if isinstance(r, tuple) else (r, "stop")
        return Completion(text, finish, 10, 10, False)
