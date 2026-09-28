# -*- coding: utf-8 -*-
"""Unit tests for GeminiApiEngine (9Router compatible)."""

import os
import pytest
from unittest.mock import patch, MagicMock
from gemini_api_engine import GeminiApiEngine, get_gemini_api_engine


def test_api_key_parsing_single_string():
    engine = GeminiApiEngine(api_keys="key1, key2, key3")
    assert engine.api_keys == ["key1", "key2", "key3"]
    assert engine.get_current_key() == "key1"


def test_api_key_parsing_list():
    engine = GeminiApiEngine(api_keys=["keyA", "keyB"])
    assert engine.api_keys == ["keyA", "keyB"]
    assert engine.get_current_key() == "keyA"


def test_api_key_parsing_semicolon_and_newline():
    engine = GeminiApiEngine(api_keys="key1;key2\nkey3")
    assert engine.api_keys == ["key1", "key2", "key3"]


def test_key_rotation_sync():
    engine = GeminiApiEngine(api_keys="k1,k2,k3")
    k1 = engine.get_current_key()
    k2 = engine.rotate_key_sync()
    k3 = engine.rotate_key_sync()
    k4 = engine.rotate_key_sync()
    assert k1 == "k1"
    assert k2 == "k2"
    assert k3 == "k3"
    assert k4 == "k1"


@pytest.mark.asyncio
async def test_key_rotation_async():
    engine = GeminiApiEngine(api_keys="key_a,key_b")
    next_k = await engine.rotate_key()
    assert next_k in ["key_a", "key_b"]


def test_get_gemini_api_engine_singleton():
    engine1 = get_gemini_api_engine()
    engine2 = get_gemini_api_engine()
    assert engine1 is engine2
    assert engine1.base_url == "http://localhost:20128/v1"
    assert engine1.default_model == "ag/gemini-3.8-flash-high"
