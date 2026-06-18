#!/usr/bin/env python3
"""本地自测：用公钥校验一份 .lic，复刻 SDK 端 LicenseVerifier 的核心逻辑。

可在任意机器（无需 Android）真实运行，用于验证签发 / 验签密码学链路与 SDK 端对称。

用法：
    python verify_license.py --license com.acme.reader.lic \
        --public-key-b64 "<gradle.properties 里的公钥>" \
        --application-id com.acme.reader \
        [--cert-sha256 AB:CD:...] [--grace-days 0] [--now 2026-06-03]

或用私钥推导公钥（开发期便捷）：
    python verify_license.py --license x.lic --private-key key.pem --application-id com.acme.reader

退出码：0 通过；非 0 表示对应失败（错误码与 SDK 端 TtsErrorCode 的 LICENSE_* 段对齐）。
"""
import argparse
import base64
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

# 与 SDK 端 com.lits.tts.sdk.TtsErrorCode 的 LICENSE_* 段对齐
LICENSE_MISSING = 1002300012
LICENSE_MALFORMED = 1002300013
LICENSE_SIGNATURE_INVALID = 1002300014
LICENSE_APP_MISMATCH = 1002300015
LICENSE_CERT_MISMATCH = 1002300016
LICENSE_EXPIRED = 1002300017
LICENSE_DEVICE_MISMATCH = 1002300018


def _norm_hex(s: str) -> str:
    return s.replace(":", "").replace(" ", "").upper()


def main() -> None:
    ap = argparse.ArgumentParser(description="本地校验 Lits TTS .lic")
    ap.add_argument("--license", required=True, help=".lic 路径")
    ap.add_argument("--public-key-b64", default=None, help="公钥 base64（同 gradle.properties）")
    ap.add_argument("--private-key", default=None, help="或给私钥 PEM，自动推导公钥")
    ap.add_argument("--password", default=None, help="私钥口令")
    ap.add_argument("--application-id", required=True, help="宿主 applicationId")
    ap.add_argument("--cert-sha256", default="", help="宿主签名证书 SHA-256（可带冒号）")
    ap.add_argument("--device-sha256", default="", help="宿主设备指纹 SHA-256（可带冒号）")
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

    try:
        env = json.loads(Path(args.license).read_text(encoding="utf-8"))
        payload_bytes = base64.b64decode(env["payload_b64"])
        sig = base64.b64decode(env["sig_b64"])
    except Exception as e:  # noqa: BLE001
        sys.exit(f"[FAIL {LICENSE_MALFORMED}] LICENSE_MALFORMED：信封解析失败 {e}")

    # 1. 验签
    try:
        pub.verify(sig, payload_bytes, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        sys.exit(f"[FAIL {LICENSE_SIGNATURE_INVALID}] LICENSE_SIGNATURE_INVALID：签名校验未通过")

    claims = json.loads(payload_bytes.decode("utf-8"))

    # 2. applicationId
    if claims.get("applicationId") != args.application_id:
        sys.exit(
            f"[FAIL {LICENSE_APP_MISMATCH}] LICENSE_APP_MISMATCH："
            f"license={claims.get('applicationId')} host={args.application_id}"
        )

    # 3. 签名证书
    want = _norm_hex(claims.get("certSha256", ""))
    if want:
        have = _norm_hex(args.cert_sha256)
        if not have:
            print("[warn] license 绑定了 certSha256，但未提供 --cert-sha256，跳过证书校验")
        elif have != want:
            sys.exit(f"[FAIL {LICENSE_CERT_MISMATCH}] LICENSE_CERT_MISMATCH：license={want} host={have}")

    # 4. 到期：到期日当天有效，再加宽限
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
            sys.exit(f"[FAIL {LICENSE_EXPIRED}] LICENSE_EXPIRED：expiresAt={expires}")

    # 5. 设备指纹
    want_dev = _norm_hex(claims.get("deviceSha256", ""))
    if want_dev:
        have_dev = _norm_hex(args.device_sha256)
        if not have_dev:
            print("[warn] license 绑定了 deviceSha256，但未提供 --device-sha256，跳过设备校验")
        elif have_dev != want_dev:
            sys.exit(f"[FAIL {LICENSE_DEVICE_MISMATCH}] LICENSE_DEVICE_MISMATCH：license={want_dev} host={have_dev}")

    print("[OK] license 校验通过")
    print(json.dumps(claims, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
