from __future__ import annotations

from ofti.core import entry_meta


def test_entry_meta_guess_validator() -> None:
    assert entry_meta._guess_validator("enableFeature") is entry_meta.bool_flag
    assert entry_meta._guess_validator("maxIter") is entry_meta.as_int
    assert entry_meta._guess_validator("timeStep") is entry_meta.as_int
    assert entry_meta._guess_validator("something") is entry_meta.non_empty


def test_entry_meta_infer_choices() -> None:
    assert entry_meta._is_word_token("word_1")
    assert not entry_meta._is_word_token("123")
    assert entry_meta._infer_scalar_choice("on") == (entry_meta.bool_flag, "boolean-like")
    assert entry_meta._infer_scalar_choice("alpha") == (entry_meta.non_empty, "word")
    assert entry_meta._infer_numeric_choice("42") == (entry_meta.as_int, "integer")
    assert entry_meta._infer_numeric_choice("3.14") == (entry_meta.as_float, "float")
