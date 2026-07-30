#!/usr/bin/env python3
"""签发一份 Amphion 离线 license（.lic）。

.lic 信封格式（与 ASR/TTS SDK 端 LicenseVerifier.kt 严格一致）：
    {"payload_b64": "<base64(UTF-8 JSON of claims)>",
     "alg": "SHA256withECDSA",
     "sig_b64": "<base64(DER ECDSA-P256 signature over the decoded payload bytes)>"}

签名覆盖的是 payload 的原始 UTF-8 字节：SDK 端 base64-decode 拿到同一串字节后直接验签，
不重新序列化，从根上规避 canonical JSON 歧义。

用法：
    python issue_license.py \
        --private-key amphion-license-private.pem \
        --device-id-file devices.txt \
        --customer "ACME Co." \
        --license-id AMP-2026-0001 \
        --device-id-salt-id DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71 \
        --expires 2027-06-03 \
        --maintenance-until 2027-06-30 \
        --install-tier LE_100K \
        --features ASR,TTS \
        --out amphion-license.lic
"""
import argparse
import base64
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
except ImportError:
    sys.exit("缺少依赖：pip install -r requirements.txt（需要 cryptography）")

DEFAULT_DEVICE_ID_SALT_ID = "DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71"


def _check_date(s: str) -> str:
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        sys.exit(f"日期格式必须是 yyyy-MM-dd：{s}")
    return s


def _normalize_device_id(value: str) -> str:
    return value.strip().upper()


def _read_device_hashes(device_file: str, salt_id: str) -> list[str]:
    if not device_file:
        return []
    devices = [
        _normalize_device_id(line)
        for line in Path(device_file).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return [
        hashlib.sha256(f"{device}{salt_id}".encode("utf-8")).hexdigest().upper()
        for device in devices
    ]


def _device_hashes(device_ids: Sequence[str], salt_id: str) -> List[str]:
    return [
        hashlib.sha256(
            f"{_normalize_device_id(device)}{salt_id}".encode("utf-8")
        ).hexdigest().upper()
        for device in device_ids
    ]


def _parse_features(raw: str) -> list[str]:
    allowed = {"ASR", "TTS"}
    features = [f.strip().upper() for f in raw.split(",") if f.strip()]
    bad = [f for f in features if f not in allowed]
    if bad:
        sys.exit(f"--features 只允许 ASR,TTS：{','.join(bad)}")
    return features


def create_license_envelope(
    *,
    private_key_path: Path,
    password: Optional[str],
    application_id: str,
    bundle_name: str,
    customer: str,
    license_id: str,
    cert_sha256: str,
    device_ids: Sequence[str],
    device_id_salt_id: str,
    issued: str,
    expires: str,
    maintenance_until: str,
    install_tier: str,
    features: Sequence[str],
    sdk_major: int,
) -> Tuple[Dict[str, str], Dict[str, Any], bytes]:
    """Create a signed license envelope without writing plaintext device IDs."""
    normalized_features = _parse_features(",".join(features))
    payload: Dict[str, Any] = {
        "applicationId": application_id,
        "bundleName": bundle_name,
        "certSha256": cert_sha256,
        "signingCertDigest": cert_sha256,
        "customer": customer,
        "deviceIdHashAlg": "SHA-256",
        "deviceIdSaltId": device_id_salt_id,
        "authorizedDeviceHashes": _device_hashes(device_ids, device_id_salt_id),
        "expiresAt": expires,
        "features": normalized_features,
        "installTier": install_tier,
        "issuedAt": issued,
        "licenseId": license_id,
        "maintenanceUntil": maintenance_until,
        "sdkMajor": sdk_major,
    }
    payload_bytes = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    priv = serialization.load_pem_private_key(
        private_key_path.read_bytes(),
        password=password.encode("utf-8") if password else None,
    )
    if not isinstance(priv, ec.EllipticCurvePrivateKey):
        raise ValueError("private key must be an EC key")
    if not isinstance(priv.curve, ec.SECP256R1):
        raise ValueError("private key must use ECDSA P-256")
    signature = priv.sign(payload_bytes, ec.ECDSA(hashes.SHA256()))
    envelope = {
        "payload_b64": base64.b64encode(payload_bytes).decode("ascii"),
        "alg": "SHA256withECDSA",
        "sig_b64": base64.b64encode(signature).decode("ascii"),
    }
    return envelope, payload, payload_bytes


def main() -> None:
    ap = argparse.ArgumentParser(description="签发 Amphion 离线 license（.lic）")
    ap.add_argument("--private-key", required=True, help="签发私钥 PEM 路径")
    ap.add_argument("--password", default=None, help="私钥口令（若 gen 时加密）")
    ap.add_argument("--application-id", default="", help="宿主 applicationId；仅写入记录，不参与 Android 绑定校验")
    ap.add_argument("--bundle-name", default="", help="HarmonyOS bundleName；仅写入记录，不参与 Android 绑定校验")
    ap.add_argument("--customer", default="", help="客户名")
    ap.add_argument("--license-id", default="", help="授权编号")
    ap.add_argument(
        "--cert-sha256",
        default="",
        help="绑定签名证书 SHA-256（可带冒号、大小写不敏感）；空=不绑证书",
    )
    ap.add_argument("--device-id-file", default="", help="授权设备 SN 清单，一行一个；空=不绑设备白名单")
    ap.add_argument(
        "--device-id-salt-id",
        default=DEFAULT_DEVICE_ID_SALT_ID,
        help=f"设备 SN 哈希盐编号；默认 {DEFAULT_DEVICE_ID_SALT_ID}",
    )
    ap.add_argument(
        "--issued", default=date.today().isoformat(), help="签发日期 yyyy-MM-dd；默认今天",
    )
    ap.add_argument("--expires", default="", help="到期日期 yyyy-MM-dd；空=永久（买断）")
    ap.add_argument("--maintenance-until", default="", help="可升级维护期 yyyy-MM-dd；空=不限制升级期")
    ap.add_argument("--install-tier", default="", help="装机量档位标识（声明性），如 LE_100K")
    ap.add_argument(
        "--features", default="ASR", help="逗号分隔的授权能力，仅允许 ASR,TTS",
    )
    ap.add_argument("--sdk-major", type=int, default=1, help="兼容的 SDK 大版本，默认 1")
    ap.add_argument("--out", default=None, help="输出 .lic 路径；默认 <applicationId>.lic 或 amphion-license.lic")
    args = ap.parse_args()

    issued = _check_date(args.issued)
    expires = _check_date(args.expires) if args.expires else ""
    maintenance_until = _check_date(args.maintenance_until) if args.maintenance_until else ""
    features = _parse_features(args.features)
    if args.device_id_file and not args.device_id_salt_id:
        sys.exit("--device-id-file 非空时必须提供 --device-id-salt-id")
    devices = [
        _normalize_device_id(line)
        for line in Path(args.device_id_file).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ] if args.device_id_file else []
    try:
        envelope, payload, _ = create_license_envelope(
            private_key_path=Path(args.private_key),
            password=args.password,
            application_id=args.application_id,
            bundle_name=args.bundle_name,
            customer=args.customer,
            license_id=args.license_id,
            cert_sha256=args.cert_sha256,
            device_ids=devices,
            device_id_salt_id=args.device_id_salt_id,
            issued=issued,
            expires=expires,
            maintenance_until=maintenance_until,
            install_tier=args.install_tier,
            features=features,
            sdk_major=args.sdk_major,
        )
    except ValueError as error:
        sys.exit(f"私钥不是 EC 密钥：{error}")

    out = Path(args.out or (f"{args.application_id}.lic" if args.application_id else "amphion-license.lic"))
    out.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ok] 已签发：{out}")
    print(f"     applicationId = {args.application_id or '(未设置)'}")
    print(f"     bundleName    = {payload['bundleName'] or '(未设置)'}")
    print(f"     customer      = {args.customer}")
    print(f"     expiresAt     = {expires or '(永久)'}")
    print(f"     maintenance   = {maintenance_until or '(不限制)'}")
    print(f"     deviceHashes  = {len(payload['authorizedDeviceHashes'])}")
    print(f"     installTier   = {args.install_tier}")
    print(f"     features      = {','.join(features) or '(无)'}")
    print("     交付给业务方放进 app 的 assets/（默认文件名 amphion-license.lic）。")


if __name__ == "__main__":
    main()
