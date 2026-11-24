import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest
from huffman import make_container, decode_container, encode_text, analyze

@pytest.mark.parametrize("text", [
    "hello world",
    "aaaaabbbbcccdde",
    "Huffman coding is lossless!",
    "🙂 café 漢字",
    "line one\nline two\twith spaces",
    "x",
    "",
])
def test_round_trip(text):
    assert decode_container(make_container(text)) == text

def test_prefix_free_codes():
    _, _, codes = encode_text("aaabbcddde")
    values = list(codes.values())
    for i, a in enumerate(values):
        for j, b in enumerate(values):
            if i != j:
                assert not b.startswith(a)

def test_more_frequent_character_not_longer_than_rare():
    _, _, codes = encode_text("aaaaaaaabbcd")
    assert len(codes["a"]) <= len(codes["d"])

def test_container_has_magic():
    assert make_container("abc").startswith(b"HF01")

def test_corrupt_file_rejected():
    with pytest.raises(ValueError):
        decode_container(b"not a huffman file")

def test_truncated_file_rejected():
    with pytest.raises(ValueError):
        decode_container(make_container("hello")[:-1])

def test_stats():
    stats = analyze("aaabbc")
    assert stats["character_count"] == 6
    assert stats["unique_characters"] == 3
    assert stats["encoded_bit_length"] > 0
