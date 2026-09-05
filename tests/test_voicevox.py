import pytest
from tts_provider import split_text_for_voicevox, concat_wav_bytes, generate_voicevox_tts
from tts_settings import is_voicevox, parse_voicevox_speaker_id


def test_voicevox_helpers():
    assert is_voicevox('voicevox') is True
    assert is_voicevox('voicevox_3') is True
    assert is_voicevox('VOICEVOX_7') is True
    assert is_voicevox('ai33pro') is False
    assert is_voicevox('edge-tts') is False

    assert parse_voicevox_speaker_id('voicevox_3') == 3
    assert parse_voicevox_speaker_id('voicevox_76') == 76
    assert parse_voicevox_speaker_id('voicevox') == 3
    assert parse_voicevox_speaker_id('invalid') == 3


def test_split_text_for_voicevox():
    text = 'こんにちは！ずんだもんなのだ。テストテキストを分割します。'
    chunks = split_text_for_voicevox(text, max_chunk_len=20)
    assert len(chunks) >= 2
    reconstructed = ''.join(chunks)
    assert 'ずんだもん' in reconstructed
    assert 'こんにちは' in reconstructed


def test_concat_wav_bytes_empty():
    assert concat_wav_bytes([]) == b''


@pytest.mark.asyncio
async def test_generate_voicevox_tts_unreachable_endpoint(tmp_path):
    output_audio = str(tmp_path / 'test.mp3')
    output_srt = str(tmp_path / 'test.srt')
    success = await generate_voicevox_tts(
        text='テスト',
        output_audio_path=output_audio,
        output_srt_path=output_srt,
        speaker_id=3,
        base_url='http://127.0.0.1:59999',
    )
    assert success is False
