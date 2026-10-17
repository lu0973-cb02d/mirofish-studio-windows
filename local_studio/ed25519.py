"""Ed25519 (RFC 8032) with no third-party dependency.

Core update packages are signed so a compromised download location cannot
make the app run foreign code. The runtime must not depend on a transitive
package for that guarantee, so this is a small, self-contained implementation
of the RFC's reference algorithm.

It is written for verifying one short manifest per update, not for bulk use or
for handling secret data in an adversarial timing setting: ``sign`` is only
used by the maintainer's offline release tooling. It is tested against the RFC
test vectors and cross-checked against ``cryptography`` where that is installed.
"""

from __future__ import annotations

import hashlib

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, -1, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)  # sqrt(-1)

PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _recover_x(y: int, sign: int) -> int | None:
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, -1, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _I % _P
    if (x * x - x2) % _P:
        return None
    if x & 1 != sign:
        x = _P - x
    return x


_GY = 4 * pow(5, -1, _P) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)  # extended coordinates (X, Y, Z, T)
_IDENTITY = (0, 1, 1, 0)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % _P
    b = (p[1] + p[0]) * (q[1] + q[0]) % _P
    c = 2 * p[3] * q[3] * _D % _P
    d = 2 * p[2] * q[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _multiply(scalar: int, point):
    result = _IDENTITY
    while scalar:
        if scalar & 1:
            result = _add(result, point)
        point = _add(point, point)
        scalar >>= 1
    return result


def _equal(p, q) -> bool:
    return (p[0] * q[2] - q[0] * p[2]) % _P == 0 and (p[1] * q[2] - q[1] * p[2]) % _P == 0


def _compress(point) -> bytes:
    zinv = pow(point[2], -1, _P)
    x, y = point[0] * zinv % _P, point[1] * zinv % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decompress(data: bytes):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _expand(seed: bytes) -> tuple[int, bytes]:
    digest = _sha512(seed)
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return scalar, digest[32:]


def public_key(seed: bytes) -> bytes:
    """Derive the 32-byte public key from a 32-byte secret seed."""
    if len(seed) != 32:
        raise ValueError("the secret seed must be 32 bytes")
    scalar, _ = _expand(seed)
    return _compress(_multiply(scalar, _G))


def sign(seed: bytes, message: bytes) -> bytes:
    """Sign ``message``. Used only by offline release tooling."""
    if len(seed) != 32:
        raise ValueError("the secret seed must be 32 bytes")
    scalar, prefix = _expand(seed)
    public = _compress(_multiply(scalar, _G))
    r = int.from_bytes(_sha512(prefix + message), "little") % _L
    point_r = _compress(_multiply(r, _G))
    k = int.from_bytes(_sha512(point_r + public + message), "little") % _L
    s = (r + k * scalar) % _L
    return point_r + s.to_bytes(32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """Return True only for a canonical, valid signature by ``public``."""
    if len(public) != PUBLIC_KEY_BYTES or len(signature) != SIGNATURE_BYTES:
        return False
    point_a = _decompress(public)
    point_r = _decompress(signature[:32])
    if point_a is None or point_r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:  # reject malleable encodings
        return False
    k = int.from_bytes(_sha512(signature[:32] + public + message), "little") % _L
    left = _multiply(8 * s, _G)
    right = _multiply(8, _add(point_r, _multiply(k, point_a)))
    return _equal(left, right)
