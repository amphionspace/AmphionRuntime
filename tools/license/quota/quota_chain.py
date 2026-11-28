"""端侧按数量离线授权（额度证书链）参考实现。

三级信任链，全部离线：

    我方根私钥 ──签──> 额度证书 amphion.quota.v1（数量 N、能力、期限、签发点公钥、签发点硬件绑定）
    签发点私钥 ──签──> 设备授权 amphion.device-license.v1（序号 seq∈[1,N]、SN 哈希、设备公钥摘要）
    设备私钥（HUKS/Keystore，不可导出）──签──> 激活请求、注销回执、运行时挑战

设备端只信任 SDK 内置的根公钥；签发点公钥来自根签过的额度证书。设备端能独立强制的是：
链上每级签名、序号上限 N、能力/期限不越过额度证书、SN 与设备密钥绑定。签发点内的计数、
硬件绑定和日志属于客户现场的软控制，靠哈希链签名日志与我方离线对账发现超发。

信封格式与现有 .lic 完全一致：{"payload_b64","alg":"SHA256withECDSA","sig_b64"}，
签名覆盖 payload 原始字节，算法 ECDSA P-256。链文件顶层没有 payload_b64，旧 SDK 解析会失败关闭。
"""
from __future__ import annotations

import base64
import binascii
import datetime as _dt
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

ALG = "SHA256withECDSA"
CHAIN_FORMAT = "amphion.quota-chain.v1"
T_SITE_ENROLL = "amphion.site-enrollment.v1"
T_QUOTA = "amphion.quota.v1"
T_ACTIVATION = "amphion.activation-request.v1"
T_DEVICE = "amphion.device-license.v1"
T_LOG = "amphion.site-log.v1"
T_DEACT = "amphion.deactivation-receipt.v1"
T_AUDIT = "amphion.site-audit.v1"
T_CHALLENGE = "amphion.device-challenge.v1"

MAX_DEVICES = 1_000_000
MAX_ENVELOPE_BYTES = 64 * 1024
MAX_AUDIT_BYTES = 256 * 1024 * 1024
ZERO_HASH = "0" * 64
FEATURES = ("ASR", "TTS")
HW_SCHEMES = ("ASCEND_NPU_VDIE_V1", "LINUX_MACHINE_ID_V1", "TEST_FIXED_V1")
REASSIGN_MODES = ("none", "receipt")

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HEX64 = re.compile(r"^[0-9A-F]{64}$")
_SALT = re.compile(r"^[A-Za-z0-9_-]{8,120}$")
_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class ChainError(Exception):
    """错误码稳定，便于设备端/运维映射；消息里不放 SN、私钥等敏感值。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------- 基础工具

def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(text: str, code: str = "MALFORMED") -> bytes:
    if not isinstance(text, str):
        raise ChainError(code, "base64 field is not a string")
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ChainError(code, "invalid base64") from error


def _no_duplicates(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            # 重复键会让不同语言的解析器读出不同值（签名相同、语义不同），一律拒绝。
            raise ChainError("MALFORMED", f"duplicate key {key!r}")
        out[key] = value
    return out


def strict_loads(raw: bytes | str, limit: int = MAX_ENVELOPE_BYTES) -> Any:
    data = raw.encode("utf-8") if isinstance(raw, str) else raw
    if len(data) > limit:
        raise ChainError("MALFORMED", "document too large")
    try:
        return json.loads(data.decode("utf-8", "strict"), object_pairs_hook=_no_duplicates,
                          parse_constant=lambda _c: (_ for _ in ()).throw(ChainError("MALFORMED", "NaN")))
    except ChainError:
        raise
    except (UnicodeError, ValueError) as error:
        raise ChainError("MALFORMED", "invalid JSON") from error


def canonical_bytes(claims: Mapping[str, Any]) -> bytes:
    return json.dumps(claims, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def today_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).date().isoformat()


def check_date(value: Any, label: str, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or not _DATE.match(value):
        raise ChainError("MALFORMED", f"{label} must be yyyy-MM-dd")
    try:
        _dt.date.fromisoformat(value)
    except ValueError as error:
        raise ChainError("MALFORMED", f"{label} is not a real date") from error
    return value


def _int(value: Any, label: str, lo: int, hi: int) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise ChainError("MALFORMED", f"{label} out of range")
    return value


def _str(value: Any, label: str, pattern: Optional[re.Pattern] = None, allow_empty: bool = False,
         max_len: int = 200) -> str:
    if not isinstance(value, str) or len(value) > max_len or (not allow_empty and not value):
        raise ChainError("MALFORMED", f"{label} invalid")
    if value and pattern is not None and not pattern.match(value):
        raise ChainError("MALFORMED", f"{label} invalid")
    return value


def _exact_keys(obj: Any, keys: Iterable[str], label: str) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise ChainError("MALFORMED", f"{label} must be an object")
    want = set(keys)
    if set(obj) != want:
        raise ChainError("MALFORMED", f"{label} fields mismatch")
    return obj


# ---------------------------------------------------------------- 密钥与信封

def generate_key() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


def spki_b64(key: ec.EllipticCurvePublicKey | ec.EllipticCurvePrivateKey) -> str:
    pub = key.public_key() if isinstance(key, ec.EllipticCurvePrivateKey) else key
    return b64e(pub.public_bytes(serialization.Encoding.DER,
                                 serialization.PublicFormat.SubjectPublicKeyInfo))


def key_id(spki: str) -> str:
    return sha256_hex(b64d(spki))


def load_public(spki: str, code: str = "MALFORMED") -> ec.EllipticCurvePublicKey:
    try:
        pub = serialization.load_der_public_key(b64d(spki, code))
    except (ValueError, TypeError) as error:
        raise ChainError(code, "bad public key") from error
    if not isinstance(pub, ec.EllipticCurvePublicKey) or not isinstance(pub.curve, ec.SECP256R1):
        raise ChainError(code, "public key must be ECDSA P-256")
    return pub


def sign_envelope(key: ec.EllipticCurvePrivateKey, claims: Mapping[str, Any]) -> Dict[str, str]:
    payload = canonical_bytes(claims)
    sig = key.sign(payload, ec.ECDSA(hashes.SHA256()))
    return {"alg": ALG, "payload_b64": b64e(payload), "sig_b64": b64e(sig)}


def open_envelope(env: Any, trusted: Sequence[str], expected_type: str,
                  sig_code: str = "SIGNATURE_INVALID") -> Tuple[bytes, Dict[str, Any]]:
    """验签后才解析 claims；claims 只来自签名覆盖的字节。返回 (payload 原始字节, claims)。"""
    env = _exact_keys(env, ("alg", "payload_b64", "sig_b64"), "envelope")
    if env["alg"] != ALG:
        raise ChainError("MALFORMED", "unsupported alg")
    payload = b64d(env["payload_b64"])
    sig = b64d(env["sig_b64"])
    if len(payload) > MAX_ENVELOPE_BYTES:
        raise ChainError("MALFORMED", "payload too large")
    ok = False
    for spki in trusted:
        try:
            load_public(spki).verify(sig, payload, ec.ECDSA(hashes.SHA256()))
            ok = True
            break
        except (InvalidSignature, ChainError):
            continue
    if not ok:
        raise ChainError(sig_code, expected_type)
    claims = strict_loads(payload)
    if not isinstance(claims, dict) or claims.get("type") != expected_type:
        # 域分离：不同用途的签名对象不能互相冒用（例如拿日志条目当设备授权）。
        raise ChainError("TYPE_MISMATCH", f"expected {expected_type}")
    return payload, claims


def device_sn_hash(sn: str, salt: str) -> str:
    normalized = sn.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{4,64}", normalized):
        raise ChainError("DEVICE_ID_INVALID", "SN must be 4-64 chars [A-Z0-9]")
    return sha256_hex((normalized + salt).encode("utf-8"))


def hardware_binding_hash(scheme: str, site_id: str, identifiers: Iterable[str]) -> List[str]:
    """每个硬件标识单独加盐哈希，签发点只需命中其中至少 minPresent 个（容忍单卡更换）。"""
    out = sorted({sha256_hex(f"{scheme}|{site_id}|{i.strip().upper()}".encode("utf-8"))
                  for i in identifiers if i.strip()})
    if not out:
        raise ChainError("HARDWARE_UNAVAILABLE", "no hardware identifiers")
    return out


# ---------------------------------------------------------------- 各类对象的结构校验

def validate_enrollment(c: Dict[str, Any]) -> Dict[str, Any]:
    _exact_keys(c, ("type", "siteId", "customer", "sitePublicKey", "hardware", "createdAt", "nonce"),
                "site enrollment")
    _str(c["siteId"], "siteId", _ID)
    _str(c["customer"], "customer")
    load_public(c["sitePublicKey"])
    hw = _exact_keys(c["hardware"], ("scheme", "hashes"), "hardware")
    if hw["scheme"] not in HW_SCHEMES:
        raise ChainError("MALFORMED", "hardware scheme")
    if (not isinstance(hw["hashes"], list) or not 1 <= len(hw["hashes"]) <= 64
            or any(not isinstance(h, str) or not _HEX64.match(h) for h in hw["hashes"])
            or len(set(hw["hashes"])) != len(hw["hashes"])):
        raise ChainError("MALFORMED", "hardware hashes")
    check_date(c["createdAt"], "createdAt")
    _str(c["nonce"], "nonce", re.compile(r"^[0-9a-f]{32}$"))
    return c


QUOTA_KEYS = ("type", "quotaId", "customer", "projectId", "issuedAt", "issueNotAfter", "licenseExpiresAt",
              "maxDevices", "features", "sdkMajor", "maintenanceUntil", "deviceIdSaltId",
              "applicationBindingMode", "bundleNames", "applicationIds", "site", "enrollmentSha256",
              "reassignment")


def validate_quota(c: Dict[str, Any]) -> Dict[str, Any]:
    _exact_keys(c, QUOTA_KEYS, "quota")
    _str(c["quotaId"], "quotaId", _ID)
    _str(c["customer"], "customer")
    _str(c["projectId"], "projectId", _ID)
    issued = check_date(c["issuedAt"], "issuedAt")
    not_after = check_date(c["issueNotAfter"], "issueNotAfter")
    lic_exp = check_date(c["licenseExpiresAt"], "licenseExpiresAt", allow_empty=True)
    if not_after < issued or (lic_exp and lic_exp < not_after):
        raise ChainError("MALFORMED", "quota dates out of order")
    _int(c["maxDevices"], "maxDevices", 1, MAX_DEVICES)
    feats = c["features"]
    if (not isinstance(feats, list) or not feats or len(set(feats)) != len(feats)
            or any(f not in FEATURES for f in feats)):
        raise ChainError("MALFORMED", "features")
    _int(c["sdkMajor"], "sdkMajor", 0, 1000)
    check_date(c["maintenanceUntil"], "maintenanceUntil", allow_empty=True)
    _str(c["deviceIdSaltId"], "deviceIdSaltId", _SALT)
    mode = c["applicationBindingMode"]
    if mode not in ("none", "allowlist"):
        raise ChainError("MALFORMED", "applicationBindingMode")
    for k in ("bundleNames", "applicationIds"):
        v = c[k]
        if not isinstance(v, list) or len(v) > 50 or any(not isinstance(x, str) or not x or len(x) > 160 for x in v):
            raise ChainError("MALFORMED", k)
    if mode == "allowlist" and not (c["bundleNames"] or c["applicationIds"]):
        raise ChainError("MALFORMED", "allowlist requires packages")
    if mode == "none" and (c["bundleNames"] or c["applicationIds"]):
        raise ChainError("MALFORMED", "packages require allowlist")
    site = _exact_keys(c["site"], ("siteId", "publicKey", "keyId", "hardware", "minHardwarePresent"), "site")
    _str(site["siteId"], "site.siteId", _ID)
    load_public(site["publicKey"])
    if site["keyId"] != key_id(site["publicKey"]):
        raise ChainError("MALFORMED", "site keyId mismatch")
    hw = _exact_keys(site["hardware"], ("scheme", "hashes"), "site.hardware")
    if hw["scheme"] not in HW_SCHEMES or not isinstance(hw["hashes"], list) or not hw["hashes"]:
        raise ChainError("MALFORMED", "site.hardware")
    _int(site["minHardwarePresent"], "minHardwarePresent", 1, len(hw["hashes"]))
    _str(c["enrollmentSha256"], "enrollmentSha256", _HEX64)
    ra = _exact_keys(c["reassignment"], ("mode", "budget"), "reassignment")
    if ra["mode"] not in REASSIGN_MODES:
        raise ChainError("MALFORMED", "reassignment.mode")
    _int(ra["budget"], "reassignment.budget", 0, MAX_DEVICES)
    if ra["mode"] == "none" and ra["budget"] != 0:
        raise ChainError("MALFORMED", "reassignment budget requires receipt mode")
    return c


def validate_activation(c: Dict[str, Any]) -> Dict[str, Any]:
    _exact_keys(c, ("type", "snHash", "deviceIdSaltId", "devicePublicKey", "platform", "bundleName",
                    "createdAt", "nonce"), "activation request")
    _str(c["snHash"], "snHash", _HEX64)
    _str(c["deviceIdSaltId"], "deviceIdSaltId", _SALT)
    load_public(c["devicePublicKey"])
    if c["platform"] not in ("harmony_arm64", "android_arm64", "simulator"):
        raise ChainError("MALFORMED", "platform")
    _str(c["bundleName"], "bundleName", allow_empty=True, max_len=160)
    check_date(c["createdAt"], "createdAt")
    _str(c["nonce"], "nonce", re.compile(r"^[0-9a-f]{32}$"))
    return c


DEVICE_KEYS = ("type", "licenseId", "quotaId", "quotaSha256", "siteKeyId", "seq", "snHash", "deviceIdSaltId",
               "devicePublicKeySha256", "features", "licenseExpiresAt", "issuedAt", "logIndex", "logPrevHash")


def validate_device(c: Dict[str, Any]) -> Dict[str, Any]:
    _exact_keys(c, DEVICE_KEYS, "device license")
    _str(c["licenseId"], "licenseId", _ID)
    _str(c["quotaId"], "quotaId", _ID)
    for k in ("quotaSha256", "siteKeyId", "snHash", "devicePublicKeySha256"):
        _str(c[k], k, _HEX64)
    _int(c["seq"], "seq", -(2 ** 31), 2 ** 31 - 1)  # 上限检查放在链校验里，给出专门错误码
    _str(c["deviceIdSaltId"], "deviceIdSaltId", _SALT)
    if not isinstance(c["features"], list) or len(set(c["features"])) != len(c["features"]):
        raise ChainError("MALFORMED", "features")
    check_date(c["licenseExpiresAt"], "licenseExpiresAt", allow_empty=True)
    check_date(c["issuedAt"], "issuedAt")
    _int(c["logIndex"], "logIndex", 0, 2 ** 40)
    if not isinstance(c["logPrevHash"], str) or not (c["logPrevHash"] == ZERO_HASH or _HEX64.match(c["logPrevHash"])):
        raise ChainError("MALFORMED", "logPrevHash")
    return c


# ---------------------------------------------------------------- 设备端校验（SDK 逻辑的参考实现）

@dataclass
class DeviceContext:
    serial: str
    bundle_name: str
    sdk_major: int
    sdk_release_date: str
    required_feature: str
    today: str
    # 设备持有密钥的证明：给定挑战字节，返回 (设备公钥 SPKI b64, 对挑战的签名)。真机上由 HUKS 完成。
    prove_key: Callable[[bytes], Tuple[str, bytes]]
    challenge: Optional[bytes] = None


@dataclass
class ChainResult:
    quota: Dict[str, Any]
    device: Dict[str, Any]
    quota_sha256: str
    device_sha256: str


def verify_chain(license_text: str, trusted_roots: Sequence[str], ctx: DeviceContext) -> ChainResult:
    if not trusted_roots:
        raise ChainError("NOT_ARMED", "no trusted root key")
    top = _exact_keys(strict_loads(license_text), ("format", "quota", "device"), "chain")
    if top["format"] != CHAIN_FORMAT:
        raise ChainError("MALFORMED", "format")

    # 1. 额度证书：只认 SDK 内置根公钥。
    q_bytes, quota = open_envelope(top["quota"], trusted_roots, T_QUOTA, "QUOTA_SIGNATURE_INVALID")
    validate_quota(quota)
    q_sha = sha256_hex(q_bytes)

    # 2. 设备授权：只认额度证书里写明的签发点公钥。
    d_bytes, dev = open_envelope(top["device"], [quota["site"]["publicKey"]], T_DEVICE, "DEVICE_SIGNATURE_INVALID")
    validate_device(dev)
    if dev["quotaSha256"] != q_sha or dev["quotaId"] != quota["quotaId"]:
        raise ChainError("QUOTA_MISMATCH", "device license references another quota")
    if dev["siteKeyId"] != quota["site"]["keyId"]:
        raise ChainError("QUOTA_MISMATCH", "site key id")

    # 3. 数量上限：设备端唯一能独立强制的计数约束。
    if not 1 <= dev["seq"] <= quota["maxDevices"]:
        raise ChainError("SEQ_OUT_OF_RANGE", f"seq={dev['seq']} max={quota['maxDevices']}")

    # 4. 签发点不能放大权限。
    if not dev["features"] or any(f not in quota["features"] for f in dev["features"]):
        raise ChainError("FEATURE_ESCALATION", "device features exceed quota")
    if ctx.required_feature not in dev["features"]:
        raise ChainError("FEATURE_MISSING", ctx.required_feature)
    if not quota["issuedAt"] <= dev["issuedAt"] <= quota["issueNotAfter"]:
        raise ChainError("ISSUE_WINDOW", "device license issued outside quota window")
    q_exp, d_exp = quota["licenseExpiresAt"], dev["licenseExpiresAt"]
    if q_exp and (not d_exp or d_exp > q_exp):
        raise ChainError("EXPIRY_ESCALATION", "device expiry beyond quota")
    if dev["deviceIdSaltId"] != quota["deviceIdSaltId"]:
        raise ChainError("QUOTA_MISMATCH", "salt")

    # 5. 运行期限 / 版本 / 维护期（策略只取自根签的额度证书）。
    if d_exp and ctx.today > d_exp:
        raise ChainError("EXPIRED", d_exp)
    if quota["sdkMajor"] > 0 and quota["sdkMajor"] != ctx.sdk_major:
        raise ChainError("SDK_MAJOR_MISMATCH", f"{quota['sdkMajor']}!={ctx.sdk_major}")
    if quota["maintenanceUntil"] and ctx.sdk_release_date and ctx.sdk_release_date > quota["maintenanceUntil"]:
        raise ChainError("MAINTENANCE_EXPIRED", quota["maintenanceUntil"])
    if quota["applicationBindingMode"] == "allowlist" and ctx.bundle_name not in (quota["bundleNames"] + quota["applicationIds"]):
        raise ChainError("APP_MISMATCH", "bundle not allowed")

    # 6. 设备绑定：SN 哈希 + 设备密钥持有证明（拷走授权文件、换机同 SN 都过不了）。
    if device_sn_hash(ctx.serial, quota["deviceIdSaltId"]) != dev["snHash"]:
        raise ChainError("DEVICE_MISMATCH", "SN")
    challenge = ctx.challenge or (T_CHALLENGE + "|" + uuid.uuid4().hex).encode("utf-8")
    spki, sig = ctx.prove_key(challenge)
    if key_id(spki) != dev["devicePublicKeySha256"]:
        raise ChainError("DEVICE_KEY_MISMATCH", "device key not the licensed one")
    try:
        load_public(spki).verify(sig, challenge, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as error:
        raise ChainError("DEVICE_KEY_MISMATCH", "challenge signature") from error
    return ChainResult(quota, dev, q_sha, sha256_hex(d_bytes))


def chain_text(quota_env: Mapping[str, str], device_env: Mapping[str, str]) -> str:
    return json.dumps({"format": CHAIN_FORMAT, "quota": quota_env, "device": device_env},
                      ensure_ascii=False, sort_keys=True, indent=1) + "\n"


# ---------------------------------------------------------------- 签发点日志与审计（双方共用的校验）

LOG_KEYS = ("type", "quotaId", "quotaSha256", "index", "prev", "at", "event", "seq", "snHash",
            "devicePublicKeySha256", "licenseSha256", "receiptSha256")
LOG_EVENTS = ("issue", "reissue", "release")


@dataclass
class LogReplay:
    head: str
    count: int
    active: Dict[str, Dict[str, Any]]      # snHash -> {seq, devicePublicKeySha256, licenseSha256}
    seq_owner: Dict[int, str]              # seq -> snHash（当前占用）
    next_seq: int
    free_seqs: List[int]
    releases: int
    license_index: Dict[str, int]          # licenseSha256 -> log index
    entry_hashes: List[str]


def replay_log(lines: Sequence[Mapping[str, str]], quota: Mapping[str, Any], quota_sha: str) -> LogReplay:
    """重放并校验整条日志：签名、哈希链、序号唯一、额度与回收预算。任何不一致都失败关闭。"""
    st = LogReplay(ZERO_HASH, 0, {}, {}, 1, [], 0, {}, [])
    for env in lines:
        apply_log_entry(st, env, quota, quota_sha)
    return st


def apply_log_entry(st: LogReplay, env: Mapping[str, str], quota: Mapping[str, Any], quota_sha: str) -> None:
    """校验并应用一条日志（重放与批量签发共用同一套规则）。"""
    i = st.count
    payload, e = open_envelope(env, [quota["site"]["publicKey"]], T_LOG, "LOG_SIGNATURE_INVALID")
    _exact_keys(e, LOG_KEYS, "log entry")
    if e["quotaId"] != quota["quotaId"] or e["quotaSha256"] != quota_sha:
        raise ChainError("LOG_QUOTA_MISMATCH", f"entry {i}")
    if e["index"] != i or e["prev"] != st.head:
        raise ChainError("LOG_CHAIN_BROKEN", f"entry {i}")
    if e["event"] not in LOG_EVENTS:
        raise ChainError("LOG_INVALID", f"entry {i} event")
    seq, sn = e["seq"], e["snHash"]
    _int(seq, "seq", 1, quota["maxDevices"])
    if e["event"] == "issue":
        if sn in st.active:
            raise ChainError("LOG_INVALID", f"entry {i} duplicate SN")
        if st.free_seqs and seq in st.free_seqs:
            st.free_seqs.remove(seq)
        elif seq == st.next_seq:
            st.next_seq += 1
        else:
            raise ChainError("LOG_INVALID", f"entry {i} seq not allocatable")
        if seq in st.seq_owner:
            raise ChainError("DUPLICATE_SEQ", f"entry {i} seq {seq}")
        st.active[sn] = {"seq": seq, "devicePublicKeySha256": e["devicePublicKeySha256"],
                         "licenseSha256": e["licenseSha256"]}
        st.seq_owner[seq] = sn
    elif e["event"] == "reissue":
        cur = st.active.get(sn)
        if cur is None or cur["seq"] != seq:
            raise ChainError("LOG_INVALID", f"entry {i} reissue without active seq")
        cur.update(devicePublicKeySha256=e["devicePublicKeySha256"], licenseSha256=e["licenseSha256"])
    else:  # release
        cur = st.active.get(sn)
        if cur is None or cur["seq"] != seq or not e["receiptSha256"]:
            raise ChainError("LOG_INVALID", f"entry {i} release")
        if quota["reassignment"]["mode"] != "receipt":
            raise ChainError("LOG_INVALID", "release not allowed by quota")
        st.releases += 1
        if st.releases > quota["reassignment"]["budget"]:
            raise ChainError("REASSIGN_BUDGET_EXCEEDED", f"entry {i}")
        del st.active[sn]
        del st.seq_owner[seq]
        st.free_seqs.append(seq)
    if e["licenseSha256"]:
        st.license_index[e["licenseSha256"]] = i
    st.head = sha256_hex(payload)
    st.entry_hashes.append(st.head)
    st.count += 1


@dataclass
class AuditReport:
    quota_id: str
    entries: int
    active_devices: int
    highest_seq: int
    releases: int
    head: str
    findings: List[str]

    @property
    def ok(self) -> bool:
        return not self.findings


def verify_audit(audit_text: str, trusted_roots: Sequence[str],
                 previous_audit_text: Optional[str] = None,
                 field_licenses: Sequence[str] = ()) -> AuditReport:
    """我方对账：额度证书 → 日志全链 → 与上次导出是否同一条链（防回滚/分叉）→ 现场抽检授权是否都在日志里。"""
    doc = _exact_keys(strict_loads(audit_text, MAX_AUDIT_BYTES), ("format", "quota", "log", "seal"), "audit")
    if doc["format"] != T_AUDIT or not isinstance(doc["log"], list):
        raise ChainError("MALFORMED", "audit format")
    q_bytes, quota = open_envelope(doc["quota"], trusted_roots, T_QUOTA, "QUOTA_SIGNATURE_INVALID")
    validate_quota(quota)
    q_sha = sha256_hex(q_bytes)
    rep = replay_log(doc["log"], quota, q_sha)
    _, seal = open_envelope(doc["seal"], [quota["site"]["publicKey"]], T_AUDIT, "AUDIT_SEAL_INVALID")
    _exact_keys(seal, ("type", "quotaId", "entries", "head", "exportedAt"), "seal")
    if seal["quotaId"] != quota["quotaId"] or seal["entries"] != rep.count or seal["head"] != rep.head:
        raise ChainError("AUDIT_SEAL_MISMATCH", "seal does not match log")

    findings: List[str] = []
    if previous_audit_text is not None:
        prev_rep = verify_audit(previous_audit_text, trusted_roots)
        if prev_rep.quota_id != quota["quotaId"]:
            findings.append("PREVIOUS_AUDIT_OTHER_QUOTA")
        elif prev_rep.entries > rep.count:
            findings.append(f"ROLLBACK: log shrank {prev_rep.entries}->{rep.count}")
        elif prev_rep.entries and rep.entry_hashes[prev_rep.entries - 1] != prev_rep.head:
            findings.append("FORK: current log does not extend previous export")
    field_seq: Dict[int, str] = {}
    for text in field_licenses:
        try:
            top = strict_loads(text)
            d_bytes, dev = open_envelope(top["device"], [quota["site"]["publicKey"]], T_DEVICE)
            validate_device(dev)
        except (ChainError, KeyError, TypeError) as error:
            findings.append(f"FIELD_LICENSE_UNVERIFIABLE: {getattr(error, 'code', 'MALFORMED')}")
            continue
        if dev["quotaId"] != quota["quotaId"]:
            findings.append("FIELD_LICENSE_OTHER_QUOTA")
            continue
        owner = field_seq.setdefault(dev["seq"], dev["snHash"])
        if owner != dev["snHash"]:
            findings.append(f"DUPLICATE_SEQ_IN_FIELD: seq={dev['seq']} held by two devices")
        d_sha = sha256_hex(d_bytes)
        if d_sha not in rep.license_index:
            # 签发点私钥签过、却不在日志里：日志被截断/回滚或签发工具被改。证据带签发点签名，不可抵赖。
            findings.append(f"OFF_LOG_LICENSE: seq={dev.get('seq')} licenseId={dev.get('licenseId')}")
        elif not 1 <= dev.get("seq", 0) <= quota["maxDevices"]:
            findings.append(f"SEQ_OUT_OF_RANGE: {dev.get('seq')}")
    highest = max(rep.seq_owner) if rep.seq_owner else 0
    return AuditReport(quota["quotaId"], rep.count, len(rep.active), highest, rep.releases, rep.head, findings)
