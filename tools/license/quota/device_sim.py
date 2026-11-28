"""设备侧模拟：用软件密钥代替 HUKS/Keystore，生成激活请求、注销回执与运行时持有证明。

真机实现要点（SDK 侧）：
- 设备密钥在 HUKS（鸿蒙）/ AndroidKeyStore 内生成，别名由 SDK 固定，不可导出；只导出公钥。
- 运行时校验每次用新随机挑战让密钥签名，再用授权里登记的公钥摘要比对后验签。
- 注销：先签回执，再删除密钥与授权文件；密钥删除后旧授权文件即使被备份恢复也无法通过持有证明。
"""
from __future__ import annotations

import uuid
from typing import Dict, Tuple

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

import quota_chain as qc


class SimDevice:
    def __init__(self, serial: str, platform: str = "simulator", bundle: str = "") -> None:
        self.serial = serial
        self.platform = platform
        self.bundle = bundle
        self.key = qc.generate_key()

    def reset_key(self) -> None:
        """恢复出厂 / 重装：HUKS 里的密钥丢失，生成新密钥。"""
        self.key = qc.generate_key()

    def prove(self, challenge: bytes) -> Tuple[str, bytes]:
        return qc.spki_b64(self.key), self.key.sign(challenge, ec.ECDSA(hashes.SHA256()))

    def activation_request(self, salt: str, today: str) -> Dict[str, str]:
        return qc.sign_envelope(self.key, {
            "type": qc.T_ACTIVATION, "snHash": qc.device_sn_hash(self.serial, salt), "deviceIdSaltId": salt,
            "devicePublicKey": qc.spki_b64(self.key), "platform": self.platform, "bundleName": self.bundle,
            "createdAt": today, "nonce": uuid.uuid4().hex})

    def deactivation_receipt(self, license_text: str, today: str) -> Dict[str, str]:
        top = qc.strict_loads(license_text)
        d_bytes, dev = qc.open_envelope(top["device"], _site_keys(top), qc.T_DEVICE)
        env = qc.sign_envelope(self.key, {
            "type": qc.T_DEACT, "quotaId": dev["quotaId"], "seq": dev["seq"], "snHash": dev["snHash"],
            "licenseSha256": qc.sha256_hex(d_bytes), "devicePublicKey": qc.spki_b64(self.key),
            "createdAt": today, "nonce": uuid.uuid4().hex})
        self.reset_key()  # 签完回执即销毁密钥，旧授权随之失效
        return env

    def context(self, today: str, *, sdk_major: int = 1, sdk_release_date: str = "", feature: str = "ASR",
                bundle: str | None = None) -> qc.DeviceContext:
        return qc.DeviceContext(serial=self.serial, bundle_name=self.bundle if bundle is None else bundle,
                                sdk_major=sdk_major, sdk_release_date=sdk_release_date, required_feature=feature,
                                today=today, prove_key=self.prove)


def _site_keys(top) -> list:
    """回执只需要读出本机授权里的字段；设备授权的签发点公钥取自同文件的额度证书（未验根签，仅取值）。"""
    quota_claims = qc.strict_loads(qc.b64d(top["quota"]["payload_b64"]))
    return [quota_claims["site"]["publicKey"]]
