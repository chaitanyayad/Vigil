"""Merkle tree over event hashes, sorted-pair sha256 (OpenZeppelin-compatible
pair ordering: hash(min(a,b) || max(a,b))), odd leaf promoted unchanged."""

import hashlib


def _pair(a: bytes, b: bytes) -> bytes:
    lo, hi = (a, b) if a <= b else (b, a)
    return hashlib.sha256(lo + hi).digest()


def merkle_root(leaves: list[bytes]) -> bytes:
    if not leaves:
        raise ValueError("empty leaf set")
    level = list(leaves)
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level) - 1, 2):
            nxt.append(_pair(level[i], level[i + 1]))
        if len(level) % 2 == 1:
            nxt.append(level[-1])
        level = nxt
    return level[0]


def merkle_proof(leaves: list[bytes], index: int) -> list[bytes]:
    """Sibling hashes bottom-up for the leaf at `index`."""
    if not 0 <= index < len(leaves):
        raise IndexError("leaf index out of range")
    proof: list[bytes] = []
    level = list(leaves)
    idx = index
    while len(level) > 1:
        sibling = idx ^ 1
        if sibling < len(level):
            proof.append(level[sibling])
        nxt = []
        for i in range(0, len(level) - 1, 2):
            nxt.append(_pair(level[i], level[i + 1]))
        if len(level) % 2 == 1:
            nxt.append(level[-1])
        idx //= 2
        level = nxt
    return proof


def verify_proof(leaf: bytes, proof: list[bytes], root: bytes) -> bool:
    acc = leaf
    for sibling in proof:
        acc = _pair(acc, sibling)
    return acc == root
