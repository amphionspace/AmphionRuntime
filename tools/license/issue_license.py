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
        --application-id com.acme.app \
        --customer "ACME Co." \
        --license-id AMP-2026-0001 \
        --device-id-file devices.txt \
        --device-id-salt-id DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71 \
        --expires 2027-06-03 \
        --maintenance-until 2027-06-30 \
        --install-tier LE_100K \
        --features ASR,TTS \
        --cert-sha256 AB:CD:...:EF \
        --out amphion-license.lic
"""
import argparse
import base64
import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

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


def _parse_features(raw: str) -> list[str]:
    allowed = {"ASR", "TTS"}
    features = [f.strip().upper() for f in raw.split(",") if f.strip()]
    bad = [f for f in features if f not in allowed]
    if bad:
        sys.exit(f"--features 只允许 ASR,TTS：{','.join(bad)}")
    return features


def main() -> None:
    ap = argparse.ArgumentParser(description="签发 Amphion 离线 license（.lic）")
    ap.add_argument("--private-key", required=True, help="签发私钥 PEM 路径")
    ap.add_argument("--password", default=None, help="私钥口令（若 gen 时加密）")
    ap.add_argument("--application-id", required=True, help="绑定的宿主 applicationId（必填）")
    ap.add_argument("--bundle-name", default="", help="HarmonyOS bundleName；默认同 applicationId")
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
    ap.add_argument("--out", default=None, help="输出 .lic 路径；默认 <applicationId>.lic")
    args = ap.parse_args()

    issued = _check_date(args.issued)
    expires = _check_date(args.expires) if args.expires else ""
    maintenance_until = _check_date(args.maintenance_until) if args.maintenance_until else ""
    features = _parse_features(args.features)
    if args.device_id_file and not args.device_id_salt_id:
        sys.exit("--device-id-file 非空时必须提供 --device-id-salt-id")
    device_hashes = _read_device_hashes(args.device_id_file, args.device_id_salt_id)

    payload = {
        "applicationId": args.application_id,
        "bundleName": args.bundle_name or args.application_id,
        "certSha256": args.cert_sha256,
        "signingCertDigest": args.cert_sha256,
        "customer": args.customer,
        "deviceIdHashAlg": "SHA-256",
        "deviceIdSaltId": args.device_id_salt_id,
        "authorizedDeviceHashes": device_hashes,
        "expiresAt": expires,
        "features": features,
        "installTier": args.install_tier,
        "issuedAt": issued,
        "licenseId": args.license_id,
        "maintenanceUntil": maintenance_until,
        "sdkMajor": args.sdk_major,
    }
    # 紧凑 + key 排序：确定性序列化（SDK 端不依赖此格式，仅为产物可复现 / 可 diff）
    payload_bytes = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")

    priv = serialization.load_pem_private_key(
        Path(args.private_key).read_bytes(),
        password=args.password.encode("utf-8") if args.password else None,
    )
    if not isinstance(priv, ec.EllipticCurvePrivateKey):
        sys.exit("私钥不是 EC 密钥；请用 gen_keypair.py 生成的 P-256 私钥")

    signature = priv.sign(payload_bytes, ec.ECDSA(hashes.SHA256()))

    envelope = {
        "payload_b64": base64.b64encode(payload_bytes).decode("ascii"),
        "alg": "SHA256withECDSA",
        "sig_b64": base64.b64encode(signature).decode("ascii"),
    }

    out = Path(args.out or f"{args.application_id}.lic")
    out.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ok] 已签发：{out}")
    print(f"     applicationId = {args.application_id}")
    print(f"     bundleName    = {payload['bundleName']}")
    print(f"     customer      = {args.customer}")
    print(f"     expiresAt     = {expires or '(永久)'}")
    print(f"     maintenance   = {maintenance_until or '(不限制)'}")
    print(f"     deviceHashes  = {len(device_hashes)}")
    print(f"     installTier   = {args.install_tier}")
    print(f"     features      = {','.join(features) or '(无)'}")
    print("     交付给业务方放进 app 的 assets/（默认文件名 amphion-license.lic）。")


if __name__ == "__main__":
    main()
