#!/usr/bin/env python3
"""vectorgen — burrow's own test vectors, computed independently of burrow.

    python3 -I tools/vectorgen.py > src/kexvec/kexvec.lu     (regenerate)
    python3 -I tools/vectorgen.py --check src/kexvec/kexvec.lu

Written from the specifications alone, sharing no code with burrow or with
any ssh implementation: X25519 from RFC 7748 §5, Ed25519 from RFC 8032
§5.1, ChaCha20 and Poly1305 from RFC 8439 §2.3–§2.5, the exchange hash from
RFC 4253 §8 with RFC 8731 §3's string-encoded public values and mpint K,
key derivation from RFC 4253 §7.2, and the packet construction from OpenSSH's
PROTOCOL.chacha20poly1305; B2's key file, userauth and channel messages
from PROTOCOL.key, RFC 4252 §7, RFC 8709 §6 and RFC 4254. Only SHA-256 and
SHA-512 come from hashlib, and HMAC-SHA1 for one hashed known_hosts name.

Every input is fixed, so the output is the same bytes on every run; the
generated module is checked in, and the gate regenerates and compares it.
"""
import hashlib
import struct
import sys

P = 2**255 - 19


# ---- RFC 7748 §5: X25519 ---------------------------------------------------
def x25519(k: bytes, u: bytes) -> bytes:
    kb = bytearray(k)
    kb[0] &= 248
    kb[31] &= 127
    kb[31] |= 64
    scalar = int.from_bytes(kb, "little")
    ub = bytearray(u)
    ub[31] &= 127
    x1 = int.from_bytes(ub, "little") % P
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    a24 = 121665
    for t in reversed(range(255)):
        kt = (scalar >> t) & 1
        swap ^= kt
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = kt
        A = (x2 + z2) % P
        AA = A * A % P
        B = (x2 - z2) % P
        BB = B * B % P
        E = (AA - BB) % P
        C = (x3 + z3) % P
        D = (x3 - z3) % P
        DA = D * A % P
        CB = C * B % P
        x3 = (DA + CB) ** 2 % P
        z3 = x1 * (DA - CB) ** 2 % P
        x2 = AA * BB % P
        z2 = E * (AA + a24 * E) % P
    if swap:
        x2, x3, z2, z3 = x3, x2, z3, z2
    return (x2 * pow(z2, P - 2, P) % P).to_bytes(32, "little")


def x25519_base(k: bytes) -> bytes:
    return x25519(k, (9).to_bytes(32, "little"))


# ---- RFC 8032 §5.1: Ed25519 ------------------------------------------------
L = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _recover_x(y, sign):
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * SQRT_M1 % P
    if x & 1 != sign:
        x = P - x
    return x


_BY = 4 * pow(5, P - 2, P) % P
BASE = (_recover_x(_BY, 0), _BY, 1, _recover_x(_BY, 0) * _BY % P)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % P
    b = (p[1] + p[0]) * (q[1] + q[0]) % P
    c = 2 * p[3] * q[3] * D % P
    d = 2 * p[2] * q[2] % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(s, p):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _encode(p):
    zi = pow(p[2], P - 2, P)
    x, y = p[0] * zi % P, p[1] * zi % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def ed25519_public(seed: bytes) -> bytes:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return _encode(_mul(a, BASE))


def ed25519_sign(seed: bytes, msg: bytes) -> bytes:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    A = _encode(_mul(a, BASE))
    r = int.from_bytes(hashlib.sha512(h[32:] + msg).digest(), "little") % L
    R = _encode(_mul(r, BASE))
    k = int.from_bytes(hashlib.sha512(R + A + msg).digest(), "little") % L
    return R + ((r + k * a) % L).to_bytes(32, "little")


# ---- RFC 8439 §2.3–§2.5: ChaCha20 and Poly1305 -----------------------------
def _rotl(v, c):
    return ((v << c) & 0xFFFFFFFF) | (v >> (32 - c))


def _qr(s, a, b, c, d):
    s[a] = (s[a] + s[b]) & 0xFFFFFFFF; s[d] = _rotl(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF; s[b] = _rotl(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b]) & 0xFFFFFFFF; s[d] = _rotl(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF; s[b] = _rotl(s[b] ^ s[c], 7)


def chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    state = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574]
    state += list(struct.unpack("<8I", key)) + [counter] + list(struct.unpack("<3I", nonce))
    w = list(state)
    for _ in range(10):
        _qr(w, 0, 4, 8, 12); _qr(w, 1, 5, 9, 13); _qr(w, 2, 6, 10, 14); _qr(w, 3, 7, 11, 15)
        _qr(w, 0, 5, 10, 15); _qr(w, 1, 6, 11, 12); _qr(w, 2, 7, 8, 13); _qr(w, 3, 4, 9, 14)
    return struct.pack("<16I", *[(w[i] + state[i]) & 0xFFFFFFFF for i in range(16)])


def chacha20_xor(key: bytes, counter: int, nonce: bytes, data: bytes) -> bytes:
    out = bytearray()
    for i in range(0, len(data), 64):
        ks = chacha20_block(key, counter + i // 64, nonce)
        out += bytes(x ^ y for x, y in zip(data[i:i + 64], ks))
    return bytes(out)


def poly1305(key: bytes, msg: bytes) -> bytes:
    r = int.from_bytes(key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s = int.from_bytes(key[16:], "little")
    p = (1 << 130) - 5
    acc = 0
    for i in range(0, len(msg), 16):
        n = int.from_bytes(msg[i:i + 16] + b"\x01", "little")
        acc = (acc + n) * r % p
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


# ---- OpenSSH PROTOCOL.chacha20poly1305 -------------------------------------
def nonce_of(seq: int) -> bytes:
    # The 64-bit nonce is the sequence number as an SSH uint64, under a
    # 64-bit block counter: in RFC 8439's 32-bit-counter, 96-bit-nonce
    # layout that is four zero bytes then the uint64, the counter's high
    # word being zero for every packet.
    return b"\x00" * 4 + struct.pack(">Q", seq)


def chachapoly_seal(key64: bytes, seq: int, frame: bytes) -> bytes:
    k2, k1 = key64[:32], key64[32:]
    n = nonce_of(seq)
    enc = chacha20_xor(k1, 0, n, frame[:4]) + chacha20_xor(k2, 1, n, frame[4:])
    return enc + poly1305(chacha20_block(k2, 0, n)[:32], enc)


# ---- RFC 4251 §5 encodings --------------------------------------------------
def u32(v):
    return struct.pack(">I", v)


def string(b):
    return u32(len(b)) + b


def namelist(names):
    return string(",".join(names).encode())


def mpint_unsigned(b):
    b = b.lstrip(b"\x00")
    if b and b[0] & 0x80:
        b = b"\x00" + b
    return string(b)


def kexinit(cookie, kex, hostkey, cipher, mac, comp):
    return (bytes([20]) + cookie + namelist(kex) + namelist(hostkey) + namelist(cipher) + namelist(cipher)
            + namelist(mac) + namelist(mac) + namelist(comp) + namelist(comp) + namelist([]) + namelist([])
            + b"\x00" + u32(0))


def frame(payload, pad_byte=0, sealed=False):
    """RFC 4253 §6 with padding >= 4: a plaintext frame a multiple of 8 as
    a whole; a sealed chacha20-poly1305 frame with packet_length a multiple
    of 8 (the length field outside the alignment, as the pinned sshd does)."""
    padlen = 4
    while ((0 if sealed else 4) + 1 + len(payload) + padlen) % 8:
        padlen += 1
    return u32(1 + len(payload) + padlen) + bytes([padlen]) + payload + bytes([pad_byte]) * padlen


def derive(K_mp, H, letter, session_id, n):
    key = hashlib.sha256(K_mp + H + letter + session_id).digest()
    while len(key) < n:
        key += hashlib.sha256(K_mp + H + key).digest()
    return key[:n]


# ---- the fixed inputs ---------------------------------------------------------
BURROW_KEX = ["curve25519-sha256", "curve25519-sha256@libssh.org", "ext-info-c", "kex-strict-c-v00@openssh.com"]
SERVER_KEX = ["mlkem768x25519-sha256", "sntrup761x25519-sha512", "sntrup761x25519-sha512@openssh.com",
              "curve25519-sha256", "curve25519-sha256@libssh.org", "ecdh-sha2-nistp256", "ecdh-sha2-nistp384",
              "ecdh-sha2-nistp521", "ext-info-s", "kex-strict-s-v00@openssh.com"]
SERVER_CIPHERS = ["chacha20-poly1305@openssh.com", "aes128-gcm@openssh.com", "aes256-gcm@openssh.com",
                  "aes128-ctr", "aes192-ctr", "aes256-ctr"]
SERVER_MACS = ["umac-64-etm@openssh.com", "umac-128-etm@openssh.com", "hmac-sha2-256-etm@openssh.com",
               "hmac-sha2-512-etm@openssh.com", "hmac-sha1-etm@openssh.com", "umac-64@openssh.com",
               "umac-128@openssh.com", "hmac-sha2-256", "hmac-sha2-512", "hmac-sha1"]


def vectors():
    v = {}
    V_C = b"SSH-2.0-burrow_0.0.0"
    V_S = b"SSH-2.0-OpenSSH_10.0p2"
    I_C = kexinit(bytes(range(16)), BURROW_KEX, ["ssh-ed25519"], ["chacha20-poly1305@openssh.com"],
                  ["hmac-sha2-256"], ["none"])
    I_S = kexinit(bytes(range(0xF0, 0x100)), SERVER_KEX,
                  ["ssh-ed25519", "ecdsa-sha2-nistp256", "rsa-sha2-512", "rsa-sha2-256"],
                  SERVER_CIPHERS, SERVER_MACS, ["none", "zlib@openssh.com"])
    c_secret = hashlib.sha256(b"burrow vector: the client's ephemeral X25519 scalar").digest()
    s_secret = hashlib.sha256(b"burrow vector: the server's ephemeral X25519 scalar").digest()
    host_seed = hashlib.sha256(b"burrow vector: the server's Ed25519 host key seed").digest()
    Q_C = x25519_base(c_secret)
    Q_S = x25519_base(s_secret)
    X = x25519(c_secret, Q_S)
    assert X == x25519(s_secret, Q_C)
    host_pub = ed25519_public(host_seed)
    K_S = string(b"ssh-ed25519") + string(host_pub)
    K_mp = mpint_unsigned(X)
    H = hashlib.sha256(string(V_C) + string(V_S) + string(I_C) + string(I_S) + string(K_S)
                       + string(Q_C) + string(Q_S) + K_mp).digest()
    sig = ed25519_sign(host_seed, H)
    sig_blob = string(b"ssh-ed25519") + string(sig)
    reply = bytes([31]) + string(K_S) + string(Q_S) + string(sig_blob)
    v.update(v_c=V_C, v_s=V_S, i_c=I_C, i_s=I_S, client_secret=c_secret, q_c=Q_C, q_s=Q_S, x_secret=X,
             k_mpint=K_mp, host_pub=host_pub, k_s=K_S, h=H, signature=sig, sig_blob=sig_blob, ecdh_reply=reply,
             fingerprint=hashlib.sha256(K_S).digest())
    # A second exchange whose X has its top bit set, so its mpint takes a
    # leading zero byte (RFC 4251 §5): searched for among fixed scalars.
    n = 0
    while True:
        s2 = hashlib.sha256(b"burrow vector: top-bit secret %d" % n).digest()
        X2 = x25519(s2, Q_S)
        if X2[0] & 0x80:
            break
        n += 1
    v.update(topbit_secret=s2, topbit_x=X2, topbit_mpint=mpint_unsigned(X2))
    # Key derivation (RFC 4253 §7.2), session_id = H of the first kex.
    for letter, name in zip(b"ABCDEF", ("iv_c2s", "iv_s2c", "key_c2s", "key_s2c", "mac_c2s", "mac_s2c")):
        v[name + "_32"] = derive(K_mp, H, bytes([letter]), H, 32)
    v["key_c2s_64"] = derive(K_mp, H, b"C", H, 64)
    v["key_s2c_64"] = derive(K_mp, H, b"D", H, 64)
    # A rekey: a second H under the first session_id.
    H2 = hashlib.sha256(H + b"burrow vector: a second exchange hash").digest()
    v["h2"] = H2
    v["key_c2s_rekey_64"] = derive(K_mp, H2, b"C", H, 64)
    # Packets: frames with zero padding, sealed at fixed sequence numbers.
    service = bytes([5]) + string(b"ssh-userauth")
    v["frame_service_request"] = frame(service)
    v["frame_newkeys"] = frame(bytes([21]))
    v["frame_ecdh_init"] = frame(bytes([30]) + string(Q_C))
    v["sealed_frame_service_request"] = frame(service, sealed=True)
    v["sealed_service_request_seq0"] = chachapoly_seal(v["key_c2s_64"], 0, frame(service, sealed=True))
    v["sealed_service_request_seq3"] = chachapoly_seal(v["key_c2s_64"], 3, frame(service, sealed=True))
    accept = bytes([6]) + string(b"ssh-userauth")
    v["sealed_service_accept_seq1"] = chachapoly_seal(v["key_s2c_64"], 1, frame(accept, sealed=True))
    big = bytes([2]) + string(bytes((i * 7) % 256 for i in range(300)))
    v["sealed_frame_ignore_300"] = frame(big, sealed=True)
    v["sealed_ignore_300_seq4294967295"] = chachapoly_seal(v["key_c2s_64"], 4294967295, frame(big, sealed=True))
    # RFC 8439 §2.5.2's Poly1305 vector and §2.4.2's ChaCha20 vector, as a
    # self-check of this generator's own primitives.
    rfc_key = bytes.fromhex("85d6be7857556d337f4452fe42d506a80103808afb0db2fd4abff6af4149f51b")
    assert poly1305(rfc_key, b"Cryptographic Forum Research Group").hex() == "a8061dc1305136c6c22b8baf0c0127a9"
    k = bytes(range(32))
    pt = b"Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, sunscreen would be it."
    ct = chacha20_xor(k, 1, bytes.fromhex("000000000000004a00000000"), pt)
    assert ct[:16].hex() == "6e2e359a2568f98041ba0728dd0d6981"
    # RFC 7748 §5.2's first X25519 vector, and RFC 8032 §7.1's TEST 1.
    assert x25519(bytes.fromhex("a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4"),
                  bytes.fromhex("e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c")).hex() == \
        "c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552"
    seed1 = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    assert ed25519_public(seed1).hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    assert ed25519_sign(seed1, b"").hex().startswith("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bac")
    # ---- B2: the OpenSSH private key format (PROTOCOL.key, its private
    # section's layout measured from the pinned ssh-keygen), for TEST 1's
    # published seed. Only the file's digest and its public line become
    # vectors: no key encoding is written into the repository.
    pub1 = ed25519_public(seed1)
    blob1 = string(b"ssh-ed25519") + string(pub1)
    comment = b"burrow vector"
    check = bytes([1, 2, 3, 4])
    sect = check + check + string(b"ssh-ed25519") + string(pub1) + string(seed1 + pub1) + string(comment)
    n = 1
    while len(sect) % 8:
        sect += bytes([n])
        n += 1
    raw = (b"openssh-key-v1\0" + string(b"none") + string(b"none") + string(b"") + u32(1)
           + string(blob1) + string(sect))
    import base64
    b64 = base64.b64encode(raw).decode()
    text = "-----BEGIN OPENSSH PRIVATE KEY-----\n" + "".join(b64[i:i + 70] + "\n" for i in range(0, len(b64), 70)) \
        + "-----END OPENSSH PRIVATE KEY-----\n"
    v["keyfile_sha256"] = hashlib.sha256(text.encode()).digest()
    v["keyfile_public_line"] = ("ssh-ed25519 " + base64.b64encode(blob1).decode() + " burrow vector\n").encode()
    v["user_blob"] = blob1
    # ---- B2: publickey authentication (RFC 4252 §7, RFC 8709 §6) for the
    # user `burrowtest`, under the first exchange's H as session id.
    user = b"burrowtest"
    head = bytes([50]) + string(user) + string(b"ssh-connection") + string(b"publickey")
    v["auth_query"] = head + b"\x00" + string(b"ssh-ed25519") + string(blob1)
    signed = string(H) + head + b"\x01" + string(b"ssh-ed25519") + string(blob1)
    v["auth_signed_data"] = signed
    usig = string(b"ssh-ed25519") + string(ed25519_sign(seed1, signed))
    v["auth_signed_request"] = head + b"\x01" + string(b"ssh-ed25519") + string(blob1) + string(usig)
    v["auth_pk_ok"] = bytes([60]) + string(b"ssh-ed25519") + string(blob1)
    # ---- B3: the session channel's messages (RFC 4254 §5.1, §6.4, §6.5,
    # §5.2), channel 0, window 2 MiB, maximum packet 32768.
    v["chan_open_session"] = bytes([90]) + string(b"session") + u32(0) + u32(2097152) + u32(32768)
    v["chan_env_git"] = bytes([98]) + u32(7) + string(b"env") + b"\x00" + string(b"GIT_PROTOCOL") + string(b"version=2")
    v["chan_exec"] = bytes([98]) + u32(7) + string(b"exec") + b"\x01" + string(b"'git-upload-pack' '/srv/a b.git'")
    v["chan_window_adjust"] = bytes([93]) + u32(7) + u32(1048576)
    v["chan_data"] = bytes([94]) + u32(7) + string(bytes([0, 255, 10, 0xc3, 0x28]))
    v["chan_eof"] = bytes([96]) + u32(7)
    v["chan_close"] = bytes([97]) + u32(7)
    # ---- B2: a hashed known_hosts name (|1|salt|hash), HMAC-SHA1 keyed by
    # the salt over the name (the construction measured against the pinned
    # ssh-keygen -H); hashlib's HMAC-SHA1 is used here as a black box.
    import hmac
    salt = hashlib.sha256(b"burrow vector: a known_hosts salt").digest()[:20]
    mac = hmac.new(salt, b"[127.0.0.1]:2222", hashlib.sha1).digest()
    v["kh_salt"] = salt
    v["kh_hashed_name"] = ("|1|" + base64.b64encode(salt).decode() + "|" + base64.b64encode(mac).decode()).encode()
    return v


def module(v):
    out = ["//! member: true",
           "//!",
           "//! burrow.kexvec — fixed test vectors, GENERATED by tools/vectorgen.py from",
           "//! the specifications (RFC 7748, 8032, 8439, 4251, 4253 §7.2 and §8, 8731 §3,",
           "//! and OpenSSH's PROTOCOL.chacha20poly1305). Do not edit: regenerate it, and",
           "//! the gate's vectors step compares the two byte for byte.",
           ""]
    for name in sorted(v):
        out.append(f"/// The `{name}` vector, as lowercase hex.")
        out.append(f"pub fn {name}() -> str {{")
        out.append(f'    "{v[name].hex()}"')
        out.append("}")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def main():
    text = module(vectors())
    if sys.argv[1:2] == ["--check"]:
        have = open(sys.argv[2], encoding="utf-8").read()
        if have != text:
            print(f"vectorgen: FAIL {sys.argv[2]} differs from a fresh generation", file=sys.stderr)
            sys.exit(1)
        print(f"vectorgen: {sys.argv[2]} matches a fresh generation ({text.count('pub fn')} vectors)")
        return
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
