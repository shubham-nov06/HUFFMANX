"""Huffman coding implementation and binary container format."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
import heapq
import json
import struct
from typing import Optional

MAGIC = b"HF01"

@dataclass
class Node:
    freq: int
    char: Optional[str] = None
    left: Optional["Node"] = None
    right: Optional["Node"] = None

    @property
    def is_leaf(self):
        return self.char is not None


def build_tree(text: str):
    if not text:
        return None, {}
    counts = Counter(text)
    heap = []
    serial = 0
    for char, freq in sorted(counts.items(), key=lambda item: ord(item[0])):
        heapq.heappush(heap, (freq, serial, Node(freq=freq, char=char)))
        serial += 1
    while len(heap) > 1:
        f1, _, left = heapq.heappop(heap)
        f2, _, right = heapq.heappop(heap)
        parent = Node(freq=f1 + f2, left=left, right=right)
        heapq.heappush(heap, (parent.freq, serial, parent))
        serial += 1
    tree = heap[0][2]
    codes = {}

    def walk(node, prefix):
        if node.is_leaf:
            codes[node.char] = prefix or "0"
            return
        walk(node.left, prefix + "0")
        walk(node.right, prefix + "1")

    walk(tree, "")
    return tree, codes


def encode_text(text: str):
    tree, codes = build_tree(text)
    bits = "".join(codes[ch] for ch in text)
    return bits, tree, codes


def pack_bits(bits: str) -> bytes:
    if not bits:
        return b""
    padding = (-len(bits)) % 8
    bits += "0" * padding
    return int(bits, 2).to_bytes(len(bits) // 8, "big")


def unpack_bits(data: bytes, bit_length: int) -> str:
    if bit_length == 0:
        return ""
    return "".join(f"{byte:08b}" for byte in data)[:bit_length]


def make_container(text: str) -> bytes:
    counts = Counter(text)
    bits, _, _ = encode_text(text)
    header = json.dumps({str(ord(ch)): n for ch, n in counts.items()},
                        separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    payload = pack_bits(bits)
    return MAGIC + struct.pack(">I", len(header)) + header + struct.pack(">Q", len(bits)) + payload


def parse_container(blob: bytes):
    if len(blob) < 16 or blob[:4] != MAGIC:
        raise ValueError("This is not a valid Huffman .huff file.")
    header_len = struct.unpack(">I", blob[4:8])[0]
    header_end = 8 + header_len
    if header_end + 8 > len(blob):
        raise ValueError("Compressed file is incomplete or corrupted.")
    try:
        raw_counts = json.loads(blob[8:header_end].decode("utf-8"))
        counts = {chr(int(k)): int(v) for k, v in raw_counts.items()}
    except Exception as exc:
        raise ValueError("Invalid frequency table in compressed file.") from exc
    bit_length = struct.unpack(">Q", blob[header_end:header_end+8])[0]
    payload = blob[header_end+8:]
    if len(payload) != (bit_length + 7) // 8:
        raise ValueError("Compressed data length does not match its header.")
    return counts, bit_length, payload


def decode_container(blob: bytes) -> str:
    counts, bit_length, payload = parse_container(blob)
    total_chars = sum(counts.values())
    if total_chars == 0:
        if bit_length != 0:
            raise ValueError("Invalid empty-file encoding.")
        return ""
    if any(v <= 0 for v in counts.values()):
        raise ValueError("Invalid character frequency.")
    tree, codes = build_tree_from_counts(counts)
    bits = unpack_bits(payload, bit_length)
    if len(codes) == 1:
        char = next(iter(codes))
        if bit_length != total_chars or any(bit != "0" for bit in bits):
            raise ValueError("Invalid single-character encoding.")
        return char * total_chars
    output = []
    node = tree
    for bit in bits:
        node = node.left if bit == "0" else node.right
        if node is None:
            raise ValueError("Invalid encoded bit sequence.")
        if node.is_leaf:
            output.append(node.char)
            node = tree
            if len(output) > total_chars:
                raise ValueError("Decoded data exceeds expected character count.")
    if node is not tree or len(output) != total_chars:
        raise ValueError("Compressed data ended unexpectedly.")
    return "".join(output)


def build_tree_from_counts(counts):
    heap = []
    serial = 0
    for char, freq in sorted(counts.items(), key=lambda item: ord(item[0])):
        heapq.heappush(heap, (freq, serial, Node(freq=freq, char=char)))
        serial += 1
    while len(heap) > 1:
        f1, _, left = heapq.heappop(heap)
        f2, _, right = heapq.heappop(heap)
        heapq.heappush(heap, (f1 + f2, serial, Node(f1 + f2, left=left, right=right)))
        serial += 1
    tree = heap[0][2] if heap else None
    codes = {}
    if tree:
        def walk(node, prefix):
            if node.is_leaf:
                codes[node.char] = prefix or "0"
            else:
                walk(node.left, prefix + "0")
                walk(node.right, prefix + "1")
        walk(tree, "")
    return tree, codes


def tree_as_dict(node):
    if node is None:
        return None
    if node.is_leaf:
        return {"name": repr(node.char), "char": node.char, "freq": node.freq, "leaf": True}
    return {"name": str(node.freq), "freq": node.freq, "leaf": False,
            "left": tree_as_dict(node.left), "right": tree_as_dict(node.right)}


def analyze(text: str):
    counts = Counter(text)
    tree, codes = build_tree(text)
    encoded_bits = sum(counts[ch] * len(code) for ch, code in codes.items())
    original_bits = len(text.encode("utf-8")) * 8
    packed_size = len(make_container(text))
    return {
        "character_count": len(text),
        "unique_characters": len(counts),
        "original_bits": original_bits,
        "encoded_bits": encoded_bits,
        "compressed_file_bytes": packed_size,
        "compressed_file_bits": packed_size * 8,
        "space_saved_percent": ((original_bits - packed_size * 8) / original_bits * 100) if original_bits else 0,
        "bit_savings_percent": ((original_bits - encoded_bits) / original_bits * 100) if original_bits else 0,
        "frequencies": [{"character": ch, "display": repr(ch), "frequency": n, "code": codes[ch]}
                        for ch, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))],
        "tree": tree_as_dict(tree),
        "encoded_preview": "".join(codes[ch] for ch in text)[:400],
        "encoded_bit_length": encoded_bits,
    }
