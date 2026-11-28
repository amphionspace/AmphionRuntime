#!/usr/bin/env python3
"""生成 SDK 端互测用例：Python 签发链文件，并用 Python verify_chain 得出期望错误码。

输出只含临时测试密钥（每次运行新生成），供 Android/Harmony 单测与 Python 结果逐条比对。
用法：python gen_sdk_fixtures.py --out <sdk>/src/test/resources/quota-chain/fixtures.json
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quota_chain as qc  # noqa: E402
from device_sim import SimDevice  # noqa: E402
from test_quota_chain import SALT, TODAY, Env  # noqa: E402


def _pkcs8(key) -> str:
    return qc.b64e(key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                     serialization.NoEncryption()))


def build(tmp: Path) -> dict:
    e = Env(tmp / "a", max_devices=3, license_expires_at="2027-12-31", maintenance_until="2027-06-30",
            bundle_names=["com.dingqiao.police"])
    other = Env(tmp / "b", max_devices=1000)
    cases = []

    def add(name, text, dev, **ctx):
        c = {"name": name, "license": text, "serial": ctx.get("serial", dev.serial),
             "deviceKeyPkcs8": _pkcs8(ctx.get("signing_key", dev.key)), "deviceKeySpki": qc.spki_b64(dev.key), "bundle": ctx.get("bundle", "com.dingqiao.police"),
             "sdkMajor": ctx.get("sdk_major", 1), "sdkReleaseDate": ctx.get("release", "2027-01-15"),
             "feature": ctx.get("feature", "ASR"), "today": ctx.get("today", TODAY)}
        try:
            r = qc.verify_chain(text, e.roots, qc.DeviceContext(
                serial=c["serial"], bundle_name=c["bundle"], sdk_major=c["sdkMajor"],
                sdk_release_date=c["sdkReleaseDate"], required_feature=c["feature"], today=c["today"],
                prove_key=ctx.get("prove", dev.prove)))
            c["expect"] = "OK"
            c["expectSeq"] = r.device["seq"]
        except qc.ChainError as error:
            c["expect"] = error.code
        cases.append(c)

    devs = [SimDevice(f"SN{i:04d}ABCD", bundle="com.dingqiao.police") for i in range(3)]
    lics = [e.activate(d) for d in devs]
    add("ok_seq1", lics[0], devs[0])
    add("ok_seq3", lics[2], devs[2])
    add("ok_lowercase_sn", lics[1], devs[1], serial="  sn0001abcd ")
    d4 = SimDevice("SN0004ABCD")
    add("seq_over_quota", e.forge_device(lics[0], seq=4, snHash=qc.device_sn_hash(d4.serial, SALT),
                                         devicePublicKeySha256=qc.key_id(qc.spki_b64(d4.key))), d4)
    top = json.loads(lics[0])
    q = json.loads(qc.b64d(top["quota"]["payload_b64"]))
    q["maxDevices"] = 100000
    tampered = dict(top, quota=dict(top["quota"], payload_b64=qc.b64e(qc.canonical_bytes(q))))
    add("quota_tampered", json.dumps(tampered), devs[0])
    od = SimDevice("SN0001ABCD")
    add("foreign_root", other.activate(od), od)
    add("other_sn", lics[0], devs[1], serial=devs[1].serial)
    clone = SimDevice("SN0000ABCD")
    add("clone_same_sn", lics[0], clone)
    add("feature_escalation", e.forge_device(lics[0], features=["ASR", "TTS"]), devs[0])
    add("expiry_escalation", e.forge_device(lics[0], licenseExpiresAt=""), devs[0])
    add("issue_window", e.forge_device(lics[0], issuedAt="2027-07-01"), devs[0])
    add("expired", lics[0], devs[0], today="2028-01-01")
    add("sdk_major", lics[0], devs[0], sdk_major=2)
    add("maintenance", lics[0], devs[0], release="2027-07-01")
    add("bundle", lics[0], devs[0], bundle="com.other.app")
    add("feature_missing", lics[0], devs[0], feature="TTS")
    raw = qc.b64d(top["device"]["payload_b64"]).decode()[:-1] + ',"seq":1}'
    sk = e.site_key()
    dup_env = {"alg": qc.ALG, "payload_b64": qc.b64e(raw.encode()),
               "sig_b64": qc.b64e(sk.sign(raw.encode(), ec.ECDSA(hashes.SHA256())))}
    add("duplicate_key", qc.chain_text(top["quota"], dup_env), devs[0])
    log0 = json.loads(e.site.log_path.read_text().splitlines()[0])
    add("type_confusion", qc.chain_text(top["quota"], log0), devs[0])
    mixed = qc.chain_text(top["quota"], json.loads(other.activate(SimDevice("SN0009ABCD")))["device"])
    add("other_site_device", mixed, devs[0])
    # 克隆机复制了原设备公钥（公开信息），但签挑战用的是自己的私钥
    thief = qc.generate_key()
    add("public_key_without_private_key", lics[0], devs[0], signing_key=thief,
        prove=lambda c: (qc.spki_b64(devs[0].key), thief.sign(c, ec.ECDSA(hashes.SHA256()))))
    # 同一签发点、同一根、同一 quotaId：拿旧版额度证书下的授权配另一版（例如续签后的）证书，只有摘要比对能拦
    qb = dict(q, maxDevices=500)
    add("device_license_on_other_quota", qc.chain_text(qc.sign_envelope(e.root, qb), top["device"]), devs[0])
    add("legacy_style_top_level", json.dumps(dict(top, payload_b64=top["device"]["payload_b64"])), devs[0])
    return {"note": "临时测试密钥，每次生成都不同；与生产信任根无关", "trustedRoots": ",".join(e.roots),
            "cases": cases}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        doc = build(Path(tmp))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    summary = {}
    for c in doc["cases"]:
        summary[c["name"]] = c["expect"]
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
