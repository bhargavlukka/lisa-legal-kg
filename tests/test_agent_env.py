import pytest

from lisa.agent.agent import sdk_env
from lisa.common.config import AgentSettings


def _s(provider_key=None, gateway_key="sk-sharedllm-x"):
    return AgentSettings(base_url="https://api.sharedllm.com/anthropic", model="z-ai/glm-flash-latest",
                         gateway_key=gateway_key, provider_key=provider_key, max_turns=30, max_revisions=2,
                         sessions_dir="sessions")


def test_pure_sharedllm_sends_only_the_virtual_key():
    env = sdk_env(_s())
    assert env["ANTHROPIC_BASE_URL"] == "https://api.sharedllm.com/anthropic"
    # gateway replies are whitespace-padded, which breaks gzip in the CLI ("Decompression error: ZlibError")
    assert env["ANTHROPIC_CUSTOM_HEADERS"] == "X-SharedLLM-Key: sk-sharedllm-x\nAccept-Encoding: identity"
    # x-api-key is forwarded upstream as a provider key (401); the gateway accepts its own key as the bearer
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-sharedllm-x" and env["ANTHROPIC_API_KEY"] == ""
    assert env["ANTHROPIC_MODEL"] == env["CLAUDE_CODE_SUBAGENT_MODEL"] == "z-ai/glm-flash-latest"


def test_byok_still_forwards_the_provider_bearer():
    env = sdk_env(_s(provider_key="prov"))
    assert env["ANTHROPIC_AUTH_TOKEN"] == "prov" and env["ANTHROPIC_API_KEY"] == ""


def test_missing_gateway_key_is_an_error():
    with pytest.raises(RuntimeError, match="SHAREDLLM_API_KEY"):
        sdk_env(_s(gateway_key=None))
