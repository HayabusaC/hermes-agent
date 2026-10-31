"""A multimodal ``/models`` entry must not abort the endpoint metadata parse.

Regression: entries shaped ``{"modalities": {"input": [...], "output": [...]}}`` (OpenAI-style
multimodal cards, e.g. an in-house gateway in front of Qwen/DeepSeek) collided with the
``input``/``output`` pricing aliases in ``_extract_pricing``. The membership test
``value not in {None, ""}`` raised ``TypeError: unhashable type: 'list'``, the whole
``fetch_endpoint_model_metadata`` parse was swallowed by its per-candidate ``except``, and the
endpoint's real ``context_length`` was replaced by the hardcoded catalog guess (Qwen3.8-Flash
-> 1M instead of the advertised 192K), which inflated the compression window.
"""
from __future__ import annotations

from agent import model_metadata

MODEL_ID = "Qwen3.8-Flash-Next-NVFP4"
PAYLOAD = {
    "object": "list",
    "data": [
        {
            "id": MODEL_ID,
            "object": "model",
            "created": 1788387826,
            "owned_by": "openai_responses",
            "name": MODEL_ID,
            "context_length": 196608,
            "modalities": {"input": ["text", "image"], "output": ["text"]},
            "capabilities": {"vision": True, "tool_call": True, "reasoning": True},
            "reasoning_options": [{"type": "effort", "values": ["low", "medium", "max"]}],
            "type": "chat",
        }
    ],
}


def test_modalities_lists_do_not_abort_models_parse():
    parsed = model_metadata._parse_models_payload(PAYLOAD)

    entry = parsed[MODEL_ID]
    assert entry["context_length"] == 196608
    # modality lists are not rates, so no pricing is invented for them
    assert "pricing" not in entry


def test_endpoint_context_length_survives_modalities_payload(monkeypatch):
    monkeypatch.setattr(
        model_metadata,
        "fetch_endpoint_model_metadata",
        lambda base_url, api_key="": model_metadata._parse_models_payload(PAYLOAD),
    )

    length = model_metadata._resolve_endpoint_context_length(
        MODEL_ID, "https://gateway.invalid/v1", api_key="test-key"
    )

    assert length == 196608


def test_scalar_pricing_aliases_still_parse():
    payload = {
        "data": [
            {
                "id": "priced-model",
                "context_length": 32768,
                "input": "0.0000003",
                "output": "0.0000012",
            }
        ]
    }

    entry = model_metadata._parse_models_payload(payload)["priced-model"]

    assert entry["pricing"]["prompt"] == "0.0000003"
    assert entry["pricing"]["completion"] == "0.0000012"
