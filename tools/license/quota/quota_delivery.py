#!/usr/bin/env python3
"""额度证书正式签发门禁：plan → issue → verify（只看最终 ZIP）→ record（Git 台账）。

与 SN 白名单的 tools/license/license_delivery.py 同一套治理约束：
- 同一把根私钥（.secure/amphion-license-private.pem），签发前核对它与四个 SDK 内置公钥一致；SDK 信任集不用改。
- 申请、入网申请都要先 plan 出摘要并人工确认 warning；issue/verify 重新计算，任何输入变化都会阻断。
- 正式签发要求干净的 Git 工作区、执行的是仓库里受控的这份工具；演练用临时根私钥必须显式 --drill，产物标记为非正式，
  不能入台账。
- verify 只打开最终 ZIP：成员集合、校验和、根签名（用 SDK 内置公钥）、额度证书确实发给这台签发点、字段与计划一致。
- record 追加 delivery/quota-delivery-history.json，按客户累计已授权数量，同一 quotaId 不能登记两次。
"""
from __future__ import annotations

import argparse
import fcntl
import io
import json
import re
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from cryptography.hazmat.primitives import serialization  # noqa: E402

import license_delivery as ld  # noqa: E402
import quota_chain as qc  # noqa: E402
from vendor_quota import issue_quota  # noqa: E402

SCHEMA = 1
PROD_KEY = ".secure/amphion-license-private.pem"
LEDGER = "delivery/quota-delivery-history.json"
ZIP_MEMBERS = frozenset({"quota.json", "README.md", "QUOTA_MANIFEST.json", "SHA256SUMS.txt"})
REQUEST_KEYS = {
    "requestId", "quotaId", "deliveryId", "customerId", "projectId", "reason", "contractRef", "issuedAt",
    "maxDevices", "features", "issueNotAfter", "licenseExpiresAt", "sdkMajor", "maintenanceUntil",
    "deviceIdSaltId", "bundleNames", "applicationIds", "minHardwarePresent", "reassignBudget", "previousQuotaId",
}
_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


class QuotaDeliveryError(RuntimeError):
    pass


def _sha(b: bytes) -> str:
    return ld._sha256_bytes(b)


def _canon(v: Any) -> bytes:
    return ld._canonical_json_bytes(v)


def _load(path: Path) -> Dict[str, Any]:
    try:
        v = qc.strict_loads(path.read_bytes(), limit=1 << 20)
    except (OSError, qc.ChainError) as error:
        raise QuotaDeliveryError(f"cannot read {path.name}: {error}") from error
    if not isinstance(v, dict):
        raise QuotaDeliveryError(f"{path.name} must be an object")
    return v


# ------------------------------------------------------------------ 申请与计划

def validate_request(r: Dict[str, Any]) -> None:
    if set(r) != REQUEST_KEYS:
        raise QuotaDeliveryError(f"request fields mismatch: missing={sorted(REQUEST_KEYS - set(r))} "
                                 f"extra={sorted(set(r) - REQUEST_KEYS)}")
    for k in ("requestId", "quotaId", "deliveryId", "projectId"):
        if not isinstance(r[k], str) or not _ID.fullmatch(r[k]):
            raise QuotaDeliveryError(f"{k} invalid")
    for k in ("customerId", "reason", "contractRef"):
        if not isinstance(r[k], str) or not r[k].strip():
            raise QuotaDeliveryError(f"{k} is required")
    if r["previousQuotaId"] and not _ID.fullmatch(str(r["previousQuotaId"])):
        raise QuotaDeliveryError("previousQuotaId invalid")
    if not isinstance(r["maxDevices"], int) or isinstance(r["maxDevices"], bool) or not 1 <= r["maxDevices"] <= qc.MAX_DEVICES:
        raise QuotaDeliveryError("maxDevices must be an integer in [1, 1e6]")
    for k in ("bundleNames", "applicationIds", "features"):
        if not isinstance(r[k], list) or not all(isinstance(x, str) and x for x in r[k]):
            raise QuotaDeliveryError(f"{k} must be a string array")
    if r["bundleNames"] and r["applicationIds"]:
        raise QuotaDeliveryError("one platform artifact per quota: fill bundleNames or applicationIds, not both")
    if r["licenseExpiresAt"] not in ("perpetual",) and not qc._DATE.fullmatch(str(r["licenseExpiresAt"])):
        raise QuotaDeliveryError("licenseExpiresAt must be perpetual or YYYY-MM-DD")
    if r["maintenanceUntil"] not in ("unlimited",) and not qc._DATE.fullmatch(str(r["maintenanceUntil"])):
        raise QuotaDeliveryError("maintenanceUntil must be unlimited or YYYY-MM-DD")


def _claims_from(r: Dict[str, Any]) -> Dict[str, Any]:
    return dict(quota_id=r["quotaId"], project_id=r["projectId"], max_devices=r["maxDevices"],
                features=r["features"], issued_at=r["issuedAt"], issue_not_after=r["issueNotAfter"],
                license_expires_at="" if r["licenseExpiresAt"] == "perpetual" else r["licenseExpiresAt"],
                sdk_major=r["sdkMajor"],
                maintenance_until="" if r["maintenanceUntil"] == "unlimited" else r["maintenanceUntil"],
                device_id_salt_id=r["deviceIdSaltId"], bundle_names=r["bundleNames"],
                application_ids=r["applicationIds"], min_hardware_present=r["minHardwarePresent"],
                reassign_budget=r["reassignBudget"])


def _enrollment_summary(enroll_env: Dict[str, str]) -> Dict[str, Any]:
    try:
        claimed = qc.strict_loads(qc.b64d(enroll_env["payload_b64"]))
        site_pub = claimed["sitePublicKey"]
    except (KeyError, TypeError) as error:
        raise QuotaDeliveryError("enrollment malformed") from error
    e_bytes, e = qc.open_envelope(enroll_env, [site_pub], qc.T_SITE_ENROLL, "ENROLLMENT_POP_INVALID")
    qc.validate_enrollment(e)
    return {"enrollmentSha256": qc.sha256_hex(e_bytes), "siteId": e["siteId"], "customer": e["customer"],
            "siteKeyId": qc.key_id(site_pub), "hardwareScheme": e["hardware"]["scheme"],
            "hardwareCount": len(e["hardware"]["hashes"])}


def _warnings(r: Dict[str, Any], enroll: Dict[str, Any], ledger: Dict[str, Any]) -> List[Dict[str, str]]:
    w: List[Dict[str, str]] = []
    if r["licenseExpiresAt"] == "perpetual":
        w.append({"code": "PERPETUAL_RUNTIME", "detail": "设备授权永久运行，靠签发窗口控制新增"})
    if r["reassignBudget"] > 0:
        w.append({"code": "REASSIGN_ENABLED", "detail": f"允许注销回收 {r['reassignBudget']} 次"})
    window = (date.fromisoformat(r["issueNotAfter"]) - date.fromisoformat(r["issuedAt"])).days
    if window > 366:
        w.append({"code": "LONG_ISSUE_WINDOW", "detail": f"签发窗口 {window} 天"})
    if not r["bundleNames"] and not r["applicationIds"]:
        w.append({"code": "NO_APP_BINDING", "detail": "不限制宿主应用包"})
    if r["minHardwarePresent"] < min(2, enroll["hardwareCount"]):
        w.append({"code": "WEAK_HARDWARE_BINDING", "detail": f"签发点只需命中 {r['minHardwarePresent']} 个硬件标识"})
    if enroll["customer"] != r["customerId"]:
        w.append({"code": "CUSTOMER_NAME_DIFFERS", "detail": f"入网申请写的是 {enroll['customer']}"})
    prior = [d for d in ledger.get("deliveries", []) if d.get("customerId") == r["customerId"]]
    if prior:
        total = sum(d["maxDevices"] for d in prior) + r["maxDevices"]
        w.append({"code": "CUSTOMER_TOTAL_INCREASES", "detail": f"该客户累计额度将达到 {total} 台"})
    if any(d.get("siteKeyId") == enroll["siteKeyId"] for d in prior):
        w.append({"code": "SITE_ALREADY_HAS_QUOTA", "detail": "同一签发点已有额度证书，确认是增补而非重复"})
    return w


def build_plan(request_path: Path, enrollment_path: Path, repo: Path) -> Dict[str, Any]:
    r = _load(request_path)
    validate_request(r)
    enroll_env = _load(enrollment_path)
    enroll = _enrollment_summary(enroll_env)
    if enroll["hardwareScheme"] == "TEST_FIXED_V1":
        raise QuotaDeliveryError("production quota must bind real hardware (TEST_FIXED_V1 refused)")
    ledger = _load_ledger(repo / LEDGER)
    if any(d.get("quotaId") == r["quotaId"] for d in ledger["deliveries"]):
        raise QuotaDeliveryError(f"quotaId already recorded: {r['quotaId']}")
    plan = {"kind": "QuotaDeliveryPlan", "schemaVersion": SCHEMA, "request": r,
            "requestSha256": _sha(_canon(r)), "enrollment": enroll, "warnings": _warnings(r, enroll, ledger)}
    plan["planSha256"] = _sha(_canon(plan))
    return plan


def _check_plan(plan_path: Path, request_path: Path, enrollment_path: Path, repo: Path) -> Dict[str, Any]:
    plan = _load(plan_path)
    expected = plan.pop("planSha256", None)
    if expected != _sha(_canon(plan)):
        raise QuotaDeliveryError("plan receipt SHA-256 mismatch")
    plan["planSha256"] = expected
    current = build_plan(request_path, enrollment_path, repo)
    for k in ("request", "requestSha256", "enrollment", "warnings"):
        if current[k] != plan[k]:
            raise QuotaDeliveryError(f"current inputs do not match approved plan: {k}")
    return plan


# ------------------------------------------------------------------ 签发

def _root_key(repo: Path, override: Optional[Path], drill: bool):
    if override is not None:
        if not drill:
            raise QuotaDeliveryError("--root-key is only for drills; pass --drill")
        return serialization.load_pem_private_key(override.read_bytes(), None), False
    if drill:
        raise QuotaDeliveryError("--drill requires an explicit temporary --root-key")
    return serialization.load_pem_private_key((repo / PROD_KEY).read_bytes(), None), True


def issue(*, repo: Path, request_path: Path, enrollment_path: Path, plan_path: Path, operator: str, out_dir: Path,
          acknowledgements: Sequence[str], root_key_path: Optional[Path] = None, drill: bool = False) -> Dict[str, Any]:
    if not operator.strip():
        raise QuotaDeliveryError("operator is required")
    plan = _check_plan(plan_path, request_path, enrollment_path, repo)
    need = {w["code"] for w in plan["warnings"]}
    if set(acknowledgements) - need:
        raise QuotaDeliveryError(f"unknown acknowledgements: {sorted(set(acknowledgements) - need)}")
    if need - set(acknowledgements):
        raise QuotaDeliveryError(f"unacknowledged plan warnings: {sorted(need - set(acknowledgements))}")
    dirty = bool(ld._git(repo, "status", "--porcelain"))
    tracked = _tool_is_tracked(repo)
    if (dirty or not tracked) and not drill:
        raise QuotaDeliveryError("production issue requires a clean Git worktree running the tracked tool")
    key, fixed_key = _root_key(repo, root_key_path, drill)
    root_pub = qc.spki_b64(key)
    embedded = _sdk_roots(repo)
    if root_pub not in embedded:
        raise QuotaDeliveryError("root key is not in the SDK embedded trust set")
    production = fixed_key and not dirty and tracked and not drill
    r = plan["request"]
    env = issue_quota(key, _load(enrollment_path), allow_test_hardware=False, **_claims_from(r))
    quota_bytes = (json.dumps(env, indent=1) + "\n").encode()
    q_sha = qc.sha256_hex(qc.b64d(env["payload_b64"]))
    manifest = {"kind": "QuotaDeliveryManifest", "schemaVersion": SCHEMA, "production": production,
                "requestId": r["requestId"], "quotaId": r["quotaId"], "deliveryId": r["deliveryId"],
                "customerId": r["customerId"], "maxDevices": r["maxDevices"], "quotaPayloadSha256": q_sha,
                "siteKeyId": plan["enrollment"]["siteKeyId"], "planSha256": plan["planSha256"],
                "toolCommit": ld._git(repo, "rev-parse", "HEAD"), "operator": operator,
                "issuedAt": r["issuedAt"]}
    readme = (f"# 额度证书 {r['quotaId']}\n\n授权数量 {r['maxDevices']} 台，签发截止 {r['issueNotAfter']}。\n"
              "在客户内网签发点执行：\n\n```bash\nsite_issuer.py --site-dir <目录> install-quota --quota quota.json "
              "--trusted-root <SDK 内置根公钥>\n```\n" + ("" if production else "\n**演练产物，不得交付客户。**\n"))
    files = {"quota.json": quota_bytes, "README.md": readme.encode(),
             "QUOTA_MANIFEST.json": (json.dumps(manifest, ensure_ascii=False, indent=1) + "\n").encode()}
    files["SHA256SUMS.txt"] = "".join(f"{_sha(b)}  {n}\n" for n, b in sorted(files.items())).encode()
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{r['deliveryId']}{'' if production else '-DRILL'}.zip"
    if zip_path.exists():
        raise QuotaDeliveryError(f"output exists: {zip_path}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in sorted(files):
            info = zipfile.ZipInfo(f"{r['deliveryId']}/{n}", date_time=(2020, 1, 1, 0, 0, 0))
            z.writestr(info, files[n])
    zip_path.write_bytes(buf.getvalue())
    receipt = {"kind": "QuotaIssuanceReceipt", "status": "ISSUED", **{k: manifest[k] for k in (
        "production", "requestId", "quotaId", "deliveryId", "customerId", "maxDevices", "quotaPayloadSha256",
        "siteKeyId", "planSha256", "toolCommit")}, "zipFileName": zip_path.name,
        "zipSha256": _sha(zip_path.read_bytes()), "operator": operator}
    (out_dir / f"{r['deliveryId']}.issuance.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=1) + "\n")
    return receipt


def _tool_is_tracked(repo: Path) -> bool:
    try:
        return (ld._git(repo, "ls-files", "--error-unmatch", "tools/license/quota/quota_delivery.py")
                == "tools/license/quota/quota_delivery.py"
                and Path(__file__).resolve() == (repo / "tools/license/quota/quota_delivery.py").resolve())
    except ld.LicenseDeliveryError:
        return False


def _sdk_roots(repo: Path) -> frozenset:
    try:
        keys = ld._embedded_public_keys(repo)
    except ld.LicenseDeliveryError as error:
        raise QuotaDeliveryError(str(error)) from error
    return next(iter(keys.values()))


# ------------------------------------------------------------------ 验收（只看最终 ZIP）

def verify(*, repo: Path, zip_path: Path, plan_path: Path, request_path: Path, enrollment_path: Path,
           operator: str) -> Dict[str, Any]:
    plan = _check_plan(plan_path, request_path, enrollment_path, repo)
    r = plan["request"]
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        prefix = f"{r['deliveryId']}/"
        if sorted(names) != sorted(prefix + n for n in ZIP_MEMBERS):
            raise QuotaDeliveryError(f"ZIP members mismatch: {names}")
        files = {n[len(prefix):]: z.read(n) for n in names}
    sums = "".join(f"{_sha(files[n])}  {n}\n" for n in sorted(files) if n != "SHA256SUMS.txt")
    if files["SHA256SUMS.txt"].decode() != sums:
        raise QuotaDeliveryError("SHA256SUMS mismatch")
    env = qc.strict_loads(files["quota.json"])
    q_bytes, quota = qc.open_envelope(env, sorted(_sdk_roots(repo)), qc.T_QUOTA, "QUOTA_SIGNATURE_INVALID")
    qc.validate_quota(quota)
    enroll = plan["enrollment"]
    expect = {"quotaId": r["quotaId"], "customer": enroll["customer"], "projectId": r["projectId"],
              "maxDevices": r["maxDevices"], "issueNotAfter": r["issueNotAfter"],
              "enrollmentSha256": enroll["enrollmentSha256"], "deviceIdSaltId": r["deviceIdSaltId"]}
    for k, v in expect.items():
        if quota[k] != v:
            raise QuotaDeliveryError(f"quota field differs from plan: {k}")
    if quota["site"]["keyId"] != enroll["siteKeyId"]:
        raise QuotaDeliveryError("quota is not bound to the enrolled site key")
    manifest = qc.strict_loads(files["QUOTA_MANIFEST.json"])
    if manifest["quotaPayloadSha256"] != qc.sha256_hex(q_bytes) or manifest["planSha256"] != plan["planSha256"]:
        raise QuotaDeliveryError("manifest does not match quota or plan")
    return {"kind": "QuotaVerificationReceipt", "status": "PASS", "production": manifest["production"],
            "quotaId": r["quotaId"], "deliveryId": r["deliveryId"], "customerId": r["customerId"],
            "maxDevices": r["maxDevices"], "siteKeyId": enroll["siteKeyId"], "planSha256": plan["planSha256"],
            "quotaPayloadSha256": manifest["quotaPayloadSha256"], "toolCommit": manifest["toolCommit"],
            "zipFileName": zip_path.name, "zipSha256": _sha(zip_path.read_bytes()), "operator": operator}


# ------------------------------------------------------------------ 台账

def _load_ledger(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"schemaVersion": SCHEMA, "deliveries": []}
    led = _load(path)
    if led.get("schemaVersion") != SCHEMA or not isinstance(led.get("deliveries"), list):
        raise QuotaDeliveryError("ledger malformed")
    return led


def record(*, repo: Path, zip_path: Path, issuance_path: Path, verification_path: Path, operator: str,
           delivered_at: str, _allow_drill: bool = False) -> Dict[str, Any]:
    datetime.strptime(delivered_at, "%Y-%m-%d")
    if not operator.strip():
        raise QuotaDeliveryError("operator is required")
    iss, ver = _load(issuance_path), _load(verification_path)
    if iss.get("status") != "ISSUED" or ver.get("status") != "PASS":
        raise QuotaDeliveryError("receipts are not ISSUED / PASS")
    if not (iss.get("production") and ver.get("production")) and not _allow_drill:
        raise QuotaDeliveryError("non-production (drill) delivery cannot be recorded")
    if not _allow_drill and ld._git(repo, "status", "--porcelain"):
        raise QuotaDeliveryError("record requires a clean Git worktree")
    for k in ("quotaId", "deliveryId", "customerId", "maxDevices", "siteKeyId", "planSha256", "quotaPayloadSha256",
              "toolCommit", "zipFileName", "zipSha256"):
        if iss.get(k) != ver.get(k):
            raise QuotaDeliveryError(f"issuance and verification disagree: {k}")
    if _sha(zip_path.read_bytes()) != ver["zipSha256"]:
        raise QuotaDeliveryError("ZIP SHA-256 does not match receipts")
    path = repo / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        led = _load_ledger(path)
        if any(d["quotaId"] == ver["quotaId"] for d in led["deliveries"]):
            raise QuotaDeliveryError(f"quotaId already recorded: {ver['quotaId']}")
        entry = {k: ver[k] for k in ("quotaId", "deliveryId", "customerId", "maxDevices", "siteKeyId",
                                     "planSha256", "quotaPayloadSha256", "toolCommit", "zipSha256")}
        entry.update(deliveredAt=delivered_at, issuedBy=iss["operator"], verifiedBy=ver["operator"],
                     recordedBy=operator)
        led["deliveries"].append(entry)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(led, ensure_ascii=False, indent=1) + "\n")
        tmp.replace(path)
    total = sum(d["maxDevices"] for d in led["deliveries"] if d["customerId"] == ver["customerId"])
    return entry | {"customerTotalDevices": total}


# ------------------------------------------------------------------ CLI

def _main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "issue", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--request", required=True, type=Path)
        p.add_argument("--enrollment", required=True, type=Path)
        if name != "plan":
            p.add_argument("--plan", required=True, type=Path)
            p.add_argument("--operator", required=True)
    sub.choices["plan"].add_argument("--out", required=True, type=Path)
    sub.choices["issue"].add_argument("--out-dir", required=True, type=Path)
    sub.choices["issue"].add_argument("--acknowledge", action="append", default=[])
    sub.choices["issue"].add_argument("--root-key", type=Path, help="仅演练：临时根私钥")
    sub.choices["issue"].add_argument("--drill", action="store_true")
    sub.choices["verify"].add_argument("--zip", required=True, type=Path)
    sub.choices["verify"].add_argument("--out", required=True, type=Path)
    p = sub.add_parser("record")
    for k in ("--zip", "--issuance", "--verification"):
        p.add_argument(k, required=True, type=Path)
    p.add_argument("--operator", required=True)
    p.add_argument("--delivered-at", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan":
            plan = build_plan(a.request, a.enrollment, a.repo)
            a.out.write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n")
            print(json.dumps({"planSha256": plan["planSha256"], "warnings": plan["warnings"]}, ensure_ascii=False, indent=1))
        elif a.cmd == "issue":
            print(json.dumps(issue(repo=a.repo, request_path=a.request, enrollment_path=a.enrollment, plan_path=a.plan,
                                   operator=a.operator, out_dir=a.out_dir, acknowledgements=a.acknowledge,
                                   root_key_path=a.root_key, drill=a.drill), ensure_ascii=False, indent=1))
        elif a.cmd == "verify":
            rec = verify(repo=a.repo, zip_path=a.zip, plan_path=a.plan, request_path=a.request,
                         enrollment_path=a.enrollment, operator=a.operator)
            a.out.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n")
            print(f"PASS production={rec['production']}")
        else:
            print(json.dumps(record(repo=a.repo, zip_path=a.zip, issuance_path=a.issuance,
                                    verification_path=a.verification, operator=a.operator,
                                    delivered_at=a.delivered_at), ensure_ascii=False, indent=1))
    except (QuotaDeliveryError, qc.ChainError, ld.LicenseDeliveryError, OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"ERROR {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
