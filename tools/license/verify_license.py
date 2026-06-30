#!/usr/bin/env python3
"""本地自测：用公钥校验一份 .lic，复刻 SDK 端 LicenseVerifier 的核心逻辑。

可在任意机器（无需 Android）真实运行，用于验证签发 / 验签密码学链路与 SDK 端对称。

用法：
    python verify_license.py --license amphion-license.lic \
        --public-key-b64 "<构建配置里的公钥>" \
        [--device-id SN001] [--cert-sha256 AB:CD:...] [--required-feature ASR] [--now 2026-06-03]

或用私钥推导公钥（开发期便捷）：
    python verify_license.py --license x.lic --private-key key.pem --device-id SN001
"""
import argparse
import base64
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
except ImportError:
    sys.exit("缺少依赖：pip install -r requirements.txt（需要 cryptography）")


def _norm_hex(s: str) -> str:
    return s.replace(":", "").replace(" ", "").upper()


def _device_hash(device_id: str, salt_id: str) -> str:
    return hashlib.sha256(f"{device_id.strip().upper()}{salt_id}".encode("utf-8")).hexdigest().upper()


def main() -> None:
    ap = argparse.ArgumentParser(description="本地校验 Amphion .lic")
    ap.add_argument("--license", required=True, help=".lic 路径")
    ap.add_argument("--public-key-b64", default=None, help="公钥 base64（同构建配置）")
    ap.add_argument("--private-key", default=None, help="或给私钥 PEM，自动推导公钥")
    ap.add_argument("--password", default=None, help="私钥口令")
    ap.add_argument("--application-id", default="", help="宿主 applicationId；仅用于人工记录，不参与绑定校验")
    ap.add_argument("--bundle-name", default="", help="宿主 HarmonyOS bundleName；仅用于人工记录，不参与绑定校验")
    ap.add_argument("--cert-sha256", default="", help="宿主签名证书 SHA-256（可带冒号）")
    ap.add_argument("--device-id", default="", help="宿主设备 SN 码；用于校验 authorizedDeviceHashes")
    ap.add_argument("--sdk-major", type=int, default=1, help="当前 SDK 大版本")
    ap.add_argument("--sdk-release-date", default="", help="当前 SDK 发布时间 yyyy-MM-dd；用于维护期校验")
    ap.add_argument("--required-feature", default="ASR", choices=["ASR", "TTS"], help="当前 SDK 要求的授权能力")
    ap.add_argument("--grace-days", type=int, default=0, help="到期宽限天数")
    ap.add_argument("--now", default=None, help="模拟当前日期 yyyy-MM-dd；默认系统今天")
    args = ap.parse_args()

    if args.public_key_b64:
        pub = serialization.load_der_public_key(base64.b64decode(args.public_key_b64))
    elif args.private_key:
        priv = serialization.load_pem_private_key(
            Path(args.private_key).read_bytes(),
            password=args.password.encode("utf-8") if args.password else None,
        )
        pub = priv.public_key()
    else:
        sys.exit("必须提供 --public-key-b64 或 --private-key 之一")

    env = json.loads(Path(args.license).read_text(encoding="utf-8"))
    payload_bytes = base64.b64decode(env["payload_b64"])
    sig = base64.b64decode(env["sig_b64"])

    try:
        pub.verify(sig, payload_bytes, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        sys.exit("[FAIL 6003] LICENSE_SIGNATURE_INVALID：签名校验未通过")

    claims = json.loads(payload_bytes.decode("utf-8"))

    want = _norm_hex(claims.get("signingCertDigest") or claims.get("certSha256", ""))
    if want:
        have = _norm_hex(args.cert_sha256)
        if not have:
            print("[warn] license 绑定了 signingCertDigest，但未提供 --cert-sha256，跳过证书校验")
        elif have != want:
            sys.exit(f"[FAIL 6005] LICENSE_CERT_MISMATCH：license={want} host={have}")

    expires = claims.get("expiresAt", "")
    if expires:
        now = (
            datetime.strptime(args.now, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if args.now
            else datetime.now(timezone.utc)
        )
        exp = datetime.strptime(expires, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        deadline = exp + timedelta(days=args.grace_days + 1)
        if now >= deadline:
            sys.exit(f"[FAIL 6006] LICENSE_EXPIRED：expiresAt={expires}")

    sdk_major = claims.get("sdkMajor", -1)
    if sdk_major >= 0 and sdk_major != args.sdk_major:
        sys.exit(f"[FAIL 6008] LICENSE_SDK_MAJOR_MISMATCH：license={sdk_major} host={args.sdk_major}")
    maintenance_until = claims.get("maintenanceUntil", "")
    if maintenance_until and args.sdk_release_date:
        release = datetime.strptime(args.sdk_release_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        maintenance = datetime.strptime(maintenance_until, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if release > maintenance:
            sys.exit(
                f"[FAIL 6009] LICENSE_MAINTENANCE_EXPIRED："
                f"maintenanceUntil={maintenance_until} sdkReleaseDate={args.sdk_release_date}"
            )

    features = {str(v).strip().upper() for v in claims.get("features", [])}
    if args.required_feature not in features:
        sys.exit(f"[FAIL 6010] LICENSE_FEATURE_MISSING：features={','.join(sorted(features))}")

    authorized = {_norm_hex(v) for v in claims.get("authorizedDeviceHashes", [])}
    if authorized:
        if not args.device_id:
            print("[warn] license 绑定了 authorizedDeviceHashes，但未提供 --device-id，跳过设备校验")
        else:
            have_dev = _device_hash(args.device_id, claims.get("deviceIdSaltId", ""))
            if have_dev not in authorized:
                sys.exit("[FAIL 6007] LICENSE_DEVICE_MISMATCH：device hash not authorized")

    print("[OK] license 校验通过")
    print(json.dumps(claims, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
