#!/usr/bin/env python3
"""我方：签发额度证书、核对签发点审计导出。

  issue-quota   校验签发点入网申请（持有证明、结构），用根私钥签 amphion.quota.v1
  audit-verify  校验审计导出：全链签名与哈希链、额度与回收预算、与上次导出是否同一条链、现场抽检授权是否入账

根私钥只在我方签发环境使用（与现有 .lic 同一把 / 同一信任集），本工具不复制、不转存私钥。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quota_chain as qc  # noqa: E402


def issue_quota(root_key: ec.EllipticCurvePrivateKey, enrollment_env: Dict[str, str], *, quota_id: str,
                project_id: str, max_devices: int, features: Sequence[str], issued_at: str, issue_not_after: str,
                license_expires_at: str, sdk_major: int, maintenance_until: str, device_id_salt_id: str,
                bundle_names: Sequence[str] = (), application_ids: Sequence[str] = (),
                min_hardware_present: int = 1, reassign_budget: int = 0,
                allow_test_hardware: bool = False) -> Dict[str, str]:
    try:
        claimed = qc.strict_loads(qc.b64d(enrollment_env["payload_b64"]))
        site_pub = claimed["sitePublicKey"]
    except (KeyError, TypeError) as error:
        raise qc.ChainError("MALFORMED", "enrollment") from error
    e_bytes, enroll = qc.open_envelope(enrollment_env, [site_pub], qc.T_SITE_ENROLL, "ENROLLMENT_POP_INVALID")
    qc.validate_enrollment(enroll)
    if enroll["hardware"]["scheme"] == "TEST_FIXED_V1" and not allow_test_hardware:
        raise qc.ChainError("TEST_HARDWARE_REFUSED", "production quota must bind real hardware")
    packages = sorted(set(bundle_names)), sorted(set(application_ids))
    claims: Dict[str, Any] = {
        "type": qc.T_QUOTA, "quotaId": quota_id, "customer": enroll["customer"], "projectId": project_id,
        "issuedAt": issued_at, "issueNotAfter": issue_not_after, "licenseExpiresAt": license_expires_at,
        "maxDevices": max_devices, "features": sorted(set(f.upper() for f in features)),
        "sdkMajor": sdk_major, "maintenanceUntil": maintenance_until, "deviceIdSaltId": device_id_salt_id,
        "applicationBindingMode": "allowlist" if (packages[0] or packages[1]) else "none",
        "bundleNames": packages[0], "applicationIds": packages[1],
        "site": {"siteId": enroll["siteId"], "publicKey": site_pub, "keyId": qc.key_id(site_pub),
                 "hardware": enroll["hardware"], "minHardwarePresent": min_hardware_present},
        "enrollmentSha256": qc.sha256_hex(e_bytes),
        "reassignment": {"mode": "receipt" if reassign_budget > 0 else "none", "budget": reassign_budget},
    }
    qc.validate_quota(claims)
    return qc.sign_envelope(root_key, claims)


def _main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("issue-quota")
    p.add_argument("--root-key", required=True, type=Path)
    p.add_argument("--enrollment", required=True, type=Path)
    p.add_argument("--quota-id", required=True)
    p.add_argument("--project-id", required=True)
    p.add_argument("--max-devices", required=True, type=int)
    p.add_argument("--features", required=True, help="ASR,TTS")
    p.add_argument("--issued-at", default=qc.today_utc())
    p.add_argument("--issue-not-after", required=True, help="签发点停止签发的日期")
    p.add_argument("--license-expires-at", required=True, help="设备授权运行到期日；perpetual 表示永久")
    p.add_argument("--sdk-major", required=True, type=int)
    p.add_argument("--maintenance-until", required=True, help="维护期截止；unlimited 表示不限")
    p.add_argument("--device-id-salt-id", required=True)
    p.add_argument("--bundle-name", action="append", default=[])
    p.add_argument("--application-id", action="append", default=[])
    p.add_argument("--min-hardware-present", type=int, default=1)
    p.add_argument("--reassign-budget", type=int, default=0, help="允许注销回收的次数；0 = 不允许回收")
    p.add_argument("--allow-test-hardware", action="store_true", help="仅内部演练：允许 TEST_FIXED_V1 硬件方案")
    p.add_argument("--out", required=True, type=Path)
    p = sub.add_parser("audit-verify")
    p.add_argument("--audit", required=True, type=Path)
    p.add_argument("--previous", type=Path)
    p.add_argument("--field-license", action="append", type=Path, default=[])
    p.add_argument("--trusted-root", action="append", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "issue-quota":
            pw = os.environ.get("AMPHION_ROOT_PASSPHRASE", "").encode() or None
            key = serialization.load_pem_private_key(a.root_key.read_bytes(), pw)
            env = issue_quota(
                key, qc.strict_loads(a.enrollment.read_bytes()), quota_id=a.quota_id, project_id=a.project_id,
                max_devices=a.max_devices, features=a.features.split(","), issued_at=a.issued_at,
                issue_not_after=a.issue_not_after,
                license_expires_at="" if a.license_expires_at == "perpetual" else a.license_expires_at,
                sdk_major=a.sdk_major,
                maintenance_until="" if a.maintenance_until == "unlimited" else a.maintenance_until,
                device_id_salt_id=a.device_id_salt_id, bundle_names=a.bundle_name,
                application_ids=a.application_id, min_hardware_present=a.min_hardware_present,
                reassign_budget=a.reassign_budget, allow_test_hardware=a.allow_test_hardware)
            if a.out.exists():
                raise qc.ChainError("OUTPUT_EXISTS", str(a.out))
            a.out.write_text(json.dumps(env, indent=1) + "\n")
            print(f"quota written: {a.out}")
        else:
            rep = qc.verify_audit(a.audit.read_text("utf-8"), a.trusted_root,
                                  a.previous.read_text("utf-8") if a.previous else None,
                                  [p.read_text("utf-8") for p in a.field_license])
            print(json.dumps(rep.__dict__ | {"ok": rep.ok}, ensure_ascii=False, indent=1))
            return 0 if rep.ok else 3
    except qc.ChainError as error:
        print(f"ERROR {error.code}: {error.detail}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
