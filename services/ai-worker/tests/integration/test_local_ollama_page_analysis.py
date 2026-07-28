"""Explicit local DSPy/Ollama vision compatibility test; never part of default CI."""

import os

import pytest
from platform_ai_worker.dspy_program import DspyOllamaVisionProgram
from platform_ai_worker.page_analyzer import DspyPageAnalyzer
from platform_clients.llm.ollama import OllamaConfig, OllamaGateway

pytestmark = pytest.mark.integration


@pytest.mark.anyio
async def test_installed_dspy_litellm_path_accepts_local_ollama_vision_input() -> None:
    if os.environ.get("RUN_OLLAMA_INTEGRATION") != "1":
        pytest.skip("set RUN_OLLAMA_INTEGRATION=1 to use the private local Ollama service")
    config = OllamaConfig(
        base_url=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"),
        vision_model=os.environ.get("OLLAMA_VISION_MODEL", "qwen3-vl:8b"),
        max_attempts=1,
    )
    gateway = OllamaGateway.create(config)
    try:
        analyzer = DspyPageAnalyzer(
            gateway,
            DspyOllamaVisionProgram(
                config=config,
                max_attempts=1,
            ),
        )
        capability = await analyzer.capabilities(force=True)
    finally:
        await gateway.close()

    assert capability.model_installed is True
    assert capability.model_advertises_vision is True
    assert capability.transport_verified is True
    assert capability.usable is True
