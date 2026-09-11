import hashlib

import pytest

from vigil.ledger.merkle import merkle_proof, merkle_root, verify_proof


def _leaves(n: int) -> list[bytes]:
    return [hashlib.sha256(f"leaf-{i}".encode()).digest() for i in range(n)]


def test_single_leaf_root_is_leaf():
    leaves = _leaves(1)
    assert merkle_root(leaves) == leaves[0]
    assert merkle_proof(leaves, 0) == []
    assert verify_proof(leaves[0], [], leaves[0])


def test_empty_leaves_raises():
    with pytest.raises(ValueError):
        merkle_root([])


@pytest.mark.parametrize("n", [2, 3, 4, 5, 7, 8, 33, 100])
def test_every_leaf_proves_membership(n):
    leaves = _leaves(n)
    root = merkle_root(leaves)
    for i in range(n):
        proof = merkle_proof(leaves, i)
        assert verify_proof(leaves[i], proof, root), f"leaf {i}/{n} failed"


@pytest.mark.parametrize("n", [2, 3, 5, 8])
def test_tampered_leaf_fails_proof(n):
    leaves = _leaves(n)
    root = merkle_root(leaves)
    for i in range(n):
        proof = merkle_proof(leaves, i)
        fake = hashlib.sha256(b"tampered").digest()
        assert not verify_proof(fake, proof, root)


def test_proof_index_out_of_range():
    with pytest.raises(IndexError):
        merkle_proof(_leaves(3), 5)


def test_root_changes_when_any_leaf_changes():
    leaves = _leaves(6)
    root = merkle_root(leaves)
    for i in range(6):
        mutated = list(leaves)
        mutated[i] = hashlib.sha256(b"x").digest()
        assert merkle_root(mutated) != root
