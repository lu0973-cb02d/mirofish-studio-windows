import os
import random

import pytest

from local_studio import ed25519

# RFC 8032, section 7.1 (TEST 1 and TEST 2): secret seed, public key, message, signature.
RFC_VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
]


@pytest.mark.parametrize("seed,public,message,signature", RFC_VECTORS)
def test_rfc_8032_vectors(seed, public, message, signature):
    seed, message = bytes.fromhex(seed), bytes.fromhex(message)
    assert ed25519.public_key(seed).hex() == public
    assert ed25519.sign(seed, message).hex() == signature
    assert ed25519.verify(bytes.fromhex(public), message, bytes.fromhex(signature))


def test_any_change_to_message_signature_or_key_is_rejected():
    seed = bytes(range(32))
    public = ed25519.public_key(seed)
    message = b'{"core_version": "1.2.0"}'
    signature = ed25519.sign(seed, message)

    assert ed25519.verify(public, message, signature)
    assert not ed25519.verify(public, message + b" ", signature)
    assert not ed25519.verify(public, b"", signature)
    for index in (0, 31, 32, 63):
        broken = bytearray(signature)
        broken[index] ^= 1
        assert not ed25519.verify(public, message, bytes(broken))
    other = ed25519.public_key(bytes(reversed(range(32))))
    assert not ed25519.verify(other, message, signature)


def test_malformed_inputs_are_rejected_without_raising():
    seed = bytes(32)
    public, signature = ed25519.public_key(seed), ed25519.sign(seed, b"x")
    assert not ed25519.verify(public[:-1], b"x", signature)
    assert not ed25519.verify(public, b"x", signature[:-1])
    assert not ed25519.verify(b"\xff" * 32, b"x", signature)           # not a curve point
    assert not ed25519.verify(public, b"x", signature[:32] + b"\xff" * 32)  # s >= group order
    assert not ed25519.verify(public, b"x", b"")
    with pytest.raises(ValueError):
        ed25519.sign(b"short", b"x")


def test_matches_an_independent_implementation():
    """Ed25519 is deterministic, so signatures must be byte-identical."""
    primitives = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    from cryptography.hazmat.primitives import serialization

    rng = random.Random(20240601)
    for _ in range(8):
        seed = bytes(rng.randrange(256) for _ in range(32))
        message = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 300)))
        reference = primitives.Ed25519PrivateKey.from_private_bytes(seed)
        reference_public = reference.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        assert ed25519.public_key(seed) == reference_public
        assert ed25519.sign(seed, message) == reference.sign(message)
        assert ed25519.verify(reference_public, message, reference.sign(message))
