#!/usr/bin/env python3
"""生成 Lits TTS 离线 license 的 ECDSA P-256 密钥对。

- 私钥：PKCS#8 PEM，写到本地文件，严禁进库（仅 issue_license.py 签发时使用）。
- 公钥：X.509 SubjectPublicKeyInfo(DER) 的 base64，单行打印；贴到
        android/TtsRuntime/gradle.properties 的 LITS_TTS_LICENSE_PUBLIC_KEY。

为什么是 P-256：SDK 端 minSdk 24，Ed25519 需 API 33 不可用；ECDSA P-256 + SHA256
（SHA256withECDSA）在 API 24 全覆盖，签名 / 公钥都短。

用法：
    python gen_keypair.py --out-private lits-tts-license-private.pem
    python gen_keypair.py --out-private key.pem --password "$PASSPHRASE"
"""
import argparse
import base64
import sys
from pathlib import Path

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
except ImportError:
    sys.exit("缺少依赖：pip install -r requirements.txt（需要 cryptography）")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="生成 Lits TTS 离线 license 的 ECDSA P-256 密钥对",
    )
    ap.add_argument(
        "--out-private",
        default="lits-tts-license-private.pem",
        help="私钥输出路径（PKCS#8 PEM）；默认 lits-tts-license-private.pem",
    )
    ap.add_argument(
        "--password",
        default=None,
        help="可选：用口令加密私钥（生产环境强烈建议）",
    )
    ap.add_argument("--force", action="store_true", help="覆盖已存在的私钥文件")
    args = ap.parse_args()

    out = Path(args.out_private)
    if out.exists() and not args.force:
        sys.exit(f"私钥文件已存在：{out}（加 --force 覆盖；切勿误删正在使用的私钥）")

    private_key = ec.generate_private_key(ec.SECP256R1())

    enc = (
        serialization.BestAvailableEncryption(args.password.encode("utf-8"))
        if args.password
        else serialization.NoEncryption()
    )
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=enc,
    )
    out.write_bytes(priv_pem)
    out.chmod(0o600)

    pub_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    pub_b64 = base64.b64encode(pub_der).decode("ascii")

    print(f"[ok] 私钥已写入：{out}（权限 600；严禁进库 / 严禁外发）")
    print("[ok] 公钥 base64（贴到 gradle.properties 的 LITS_TTS_LICENSE_PUBLIC_KEY）：")
    print(pub_b64)


if __name__ == "__main__":
    main()
