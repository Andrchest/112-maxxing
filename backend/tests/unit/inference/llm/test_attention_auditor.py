"""Offline attention smoke: real tiny random Llama, no downloaded weights or GPU.

This verifies masking/tensor plumbing, NOT emergency-domain grading quality.
"""

from types import SimpleNamespace

import pytest
from app.application.reports.ml_audit import Criterion, Source
from app.inference.llm.attention_auditor import (
    LocalAttentionEngine,
    attention_evidence,
    force_binary_token,
)


def test_attention_evidence_uses_only_operator_offsets_even_if_context_peak_is_larger():
    source = Source(id="operator", text="Кровь есть?", kind="dialogue")
    evidence = attention_evidence(
        (source,),
        [(10, 21)],
        [(0, 9), (10, 15), (16, 21)],
        [0.9, 0.07, 0.03],
    )
    assert evidence.quote == source.text[evidence.start : evidence.end]
    assert evidence.source_id == "operator"
    assert evidence.start == 0


def test_missing_operator_attention_is_unknown_not_context_evidence():
    with pytest.raises(ValueError):
        attention_evidence(
            (Source(id="op", text="нет", kind="dialogue"),),
            [(10, 13)],
            [(0, 8), (10, 13)],
            [1.0, 0.0],
        )


def test_logit_mask_forces_yes_or_no_even_when_other_tokens_are_more_likely():
    torch = pytest.importorskip("torch")
    logits = torch.tensor([1000.0, -10.0, -20.0, 999.0])
    assert force_binary_token(logits, 1, 2) == 1
    logits[2] = -5
    assert force_binary_token(logits, 1, 2) == 2


def test_real_tiny_llama_forward_obeys_mask_and_exposes_attentions():
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from tokenizers import Tokenizer, models, pre_tokenizers
    from transformers import LlamaConfig, LlamaForCausalLM, PreTrainedTokenizerFast

    raw = Tokenizer(
        models.WordLevel(
            {"[UNK]": 0, "да": 1, "нет": 2, "Кровь": 4, "есть": 5},
            unk_token="[UNK]",
        )
    )
    raw.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=raw, unk_token="[UNK]")
    model = LlamaForCausalLM(
        LlamaConfig(
            vocab_size=16,
            hidden_size=32,
            intermediate_size=64,
            num_hidden_layers=2,
            num_attention_heads=4,
            num_key_value_heads=2,
            max_position_embeddings=512,
            attn_implementation="eager",
        )
    ).eval()
    captured = SimpleNamespace()

    def before(module, args, kwargs):
        captured.mask = kwargs["attention_mask"].clone()

    def after(module, args, output):
        captured.attentions = output.attentions

    model.register_forward_pre_hook(before, with_kwargs=True)
    model.register_forward_hook(after)
    engine = LocalAttentionEngine("unused", max_tokens=512)
    engine.model, engine.tokenizer = model, tokenizer
    result = engine.judge(
        Criterion(
            id="x", category="Safety", question="Спросил о раненых?", weight=1, source="dialogue"
        ),
        (Source(id="operator", text="Кровь есть?", kind="dialogue"),),
        ("Пожар",),
    )
    assert result.issue is None
    assert result.decision_token in ("да", "нет")
    assert result.passed == (result.decision_token == "да")
    assert len(captured.attentions) == 2
    blocked = captured.mask[0, 0, -1] < 0
    assert blocked.any() and (~blocked).any()
    for layer in captured.attentions:
        assert torch.all(layer[0, :, -1, blocked] == 0)
    for evidence in result.evidence:
        assert evidence.quote == "Кровь есть?"[evidence.start : evidence.end]
