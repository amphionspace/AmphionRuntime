"""额度证书签发门禁：计划锁定、warning 确认、SDK 信任集比对、ZIP 验收、台账。临时 Git 仓库 + 临时根私钥。"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quota_chain as qc  # noqa: E402
import quota_delivery as qd  # noqa: E402
from site_issuer import Site  # noqa: E402

SDK_FILES = {
    "asr/android/gradle.properties": "AMPHION_LICENSE_PUBLIC_KEY={k}\n",
    "tts/android/gradle.properties": "AMPHION_LICENSE_PUBLIC_KEY={k}\n",
    "asr/harmony/sdk/src/main/ets/com/amphion/asr/License.ets": "const LICENSE_PUBLIC_KEY_B64: string = '{k}';\n",
    "tts/harmony/sdk/src/main/ets/License.ets": "const LICENSE_PUBLIC_KEY_B64: string = '{k}';\n",
}


def _request(**kw):
    r = {"requestId": "REQ-Q-001", "quotaId": "Q-DQ-001", "deliveryId": "DQ-QUOTA-001", "customerId": "Dingqiao",
         "projectId": "DQ-EDGE", "reason": "首批端侧", "contractRef": "HT-2026-001", "issuedAt": "2026-11-27",
         "maxDevices": 500, "features": ["ASR"], "issueNotAfter": "2027-06-30", "licenseExpiresAt": "perpetual",
         "sdkMajor": 1, "maintenanceUntil": "2027-11-27", "deviceIdSaltId": "DQ-TEST-QUOTA-SALT-0001",
         "bundleNames": ["com.dingqiao.police"], "applicationIds": [], "minHardwarePresent": 1,
         "reassignBudget": 0, "previousQuotaId": ""}
    r.update(kw)
    return r


class Repo:
    def __init__(self, tmp: Path, sdk_key=None):
        self.root_key = qc.generate_key()
        self.root_pem = tmp / "root.pem"
        self.root_pem.write_bytes(self.root_key.private_bytes(serialization.Encoding.PEM,
                                                              serialization.PrivateFormat.PKCS8,
                                                              serialization.NoEncryption()))
        self.repo = tmp / "repo"
        for rel, tpl in SDK_FILES.items():
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(tpl.format(k=qc.spki_b64(sdk_key or self.root_key)))
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"],
                       check=True)
        site = Site(tmp / "site", passphrase="correct horse battery", hardware=lambda _s: ["VDIE-1", "VDIE-2"])
        self.enroll = tmp / "enrollment.json"
        self.enroll.write_text(json.dumps(site.init("Dingqiao", "ASCEND_NPU_VDIE_V1", "2026-11-27")))
        self.request = tmp / "request.json"
        self.request.write_text(json.dumps(_request(), ensure_ascii=False))
        self.plan = tmp / "plan.json"
        self.out = tmp / "out"

    def make_plan(self):
        plan = qd.build_plan(self.request, self.enroll, self.repo)
        self.plan.write_text(json.dumps(plan, ensure_ascii=False))
        return plan

    def issue(self, ack=None, **kw):
        plan = json.loads(self.plan.read_text())
        acks = [w["code"] for w in plan["warnings"]] if ack is None else ack
        args = dict(repo=self.repo, request_path=self.request, enrollment_path=self.enroll, plan_path=self.plan,
                    operator="op-a", out_dir=self.out, acknowledgements=acks, root_key_path=self.root_pem, drill=True)
        args.update(kw)
        return qd.issue(**args)

    def verify(self, zip_path):
        return qd.verify(repo=self.repo, zip_path=zip_path, plan_path=self.plan, request_path=self.request,
                         enrollment_path=self.enroll, operator="op-b")


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path)


def test_plan_issue_verify_record(repo, tmp_path):
    plan = repo.make_plan()
    assert {w["code"] for w in plan["warnings"]} == {"PERPETUAL_RUNTIME", "WEAK_HARDWARE_BINDING"}
    iss = repo.issue()
    assert iss["production"] is False and iss["zipFileName"].endswith("-DRILL.zip")
    ver = repo.verify(repo.out / iss["zipFileName"])
    assert ver["status"] == "PASS" and ver["maxDevices"] == 500
    (tmp_path / "iss.json").write_text(json.dumps(iss))
    (tmp_path / "ver.json").write_text(json.dumps(ver))
    with pytest.raises(qd.QuotaDeliveryError, match="non-production"):
        qd.record(repo=repo.repo, zip_path=repo.out / iss["zipFileName"], issuance_path=tmp_path / "iss.json",
                  verification_path=tmp_path / "ver.json", operator="op-c", delivered_at="2026-11-28")
    entry = qd.record(repo=repo.repo, zip_path=repo.out / iss["zipFileName"], issuance_path=tmp_path / "iss.json",
                      verification_path=tmp_path / "ver.json", operator="op-c", delivered_at="2026-11-28",
                      _allow_drill=True)
    assert entry["customerTotalDevices"] == 500
    with pytest.raises(qd.QuotaDeliveryError, match="already recorded"):
        qd.record(repo=repo.repo, zip_path=repo.out / iss["zipFileName"], issuance_path=tmp_path / "iss.json",
                  verification_path=tmp_path / "ver.json", operator="op-c", delivered_at="2026-11-28",
                  _allow_drill=True)
    # 再申请同一 quotaId 在 plan 就被拦；换 quotaId 则提示客户累计额度和同一签发点
    with pytest.raises(qd.QuotaDeliveryError, match="already recorded"):
        repo.make_plan()
    repo.request.write_text(json.dumps(_request(quotaId="Q-DQ-002", deliveryId="DQ-QUOTA-002", maxDevices=300)))
    codes = {w["code"] for w in repo.make_plan()["warnings"]}
    assert {"CUSTOMER_TOTAL_INCREASES", "SITE_ALREADY_HAS_QUOTA"} <= codes


def test_request_changed_after_plan_is_blocked(repo):
    repo.make_plan()
    repo.request.write_text(json.dumps(_request(maxDevices=5000)))
    with pytest.raises(qd.QuotaDeliveryError, match="do not match approved plan"):
        repo.issue()


def test_edited_plan_receipt_is_blocked(repo):
    repo.make_plan()
    plan = json.loads(repo.plan.read_text())
    plan["warnings"] = []
    repo.plan.write_text(json.dumps(plan))
    with pytest.raises(qd.QuotaDeliveryError, match="SHA-256 mismatch"):
        repo.issue()


def test_unacknowledged_warning_blocks_issue(repo):
    repo.make_plan()
    with pytest.raises(qd.QuotaDeliveryError, match="unacknowledged"):
        repo.issue(ack=["PERPETUAL_RUNTIME"])


def test_root_key_outside_sdk_trust_set_is_refused(tmp_path):
    r = Repo(tmp_path, sdk_key=qc.generate_key())
    r.make_plan()
    with pytest.raises(qd.QuotaDeliveryError, match="trust set"):
        r.issue()


def test_temporary_key_requires_drill_and_production_requires_clean_tracked_tool(repo):
    repo.make_plan()
    with pytest.raises(qd.QuotaDeliveryError, match="clean Git worktree"):
        repo.issue(drill=False, root_key_path=None)
    with pytest.raises(qd.QuotaDeliveryError, match="only for drills"):
        qd._root_key(repo.repo, repo.root_pem, drill=False)


def test_test_hardware_enrollment_refused(tmp_path):
    r = Repo(tmp_path)
    site = Site(tmp_path / "site2", passphrase="correct horse battery", hardware=lambda _s: ["X"])
    r.enroll.write_text(json.dumps(site.init("Dingqiao", "TEST_FIXED_V1", "2026-11-27")))
    with pytest.raises(qd.QuotaDeliveryError, match="TEST_FIXED_V1"):
        r.make_plan()


def test_request_schema_is_strict(repo):
    for bad in (_request(maxDevices=0), _request(maxDevices=True), _request(extra=1),
                _request(bundleNames=["a"], applicationIds=["b"]), _request(contractRef=" "),
                _request(licenseExpiresAt="forever")):
        with pytest.raises(qd.QuotaDeliveryError):
            qd.validate_request(bad)


def test_tampered_zip_fails_verification(repo, tmp_path):
    repo.make_plan()
    iss = repo.issue()
    src = repo.out / iss["zipFileName"]
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(bad, "w") as zout:
        for n in zin.namelist():
            data = zin.read(n)
            if n.endswith("README.md"):
                data += b"\n tampered"
            zout.writestr(n, data)
    with pytest.raises(qd.QuotaDeliveryError, match="SHA256SUMS"):
        repo.verify(bad)
    extra = tmp_path / "extra.zip"
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(extra, "w") as zout:
        for n in zin.namelist():
            zout.writestr(n, zin.read(n))
        zout.writestr(f"{iss['deliveryId']}/private.pem", b"x")
    with pytest.raises(qd.QuotaDeliveryError, match="members"):
        repo.verify(extra)


def test_issued_quota_installs_on_the_enrolled_site(repo, tmp_path):
    repo.make_plan()
    iss = repo.issue()
    with zipfile.ZipFile(repo.out / iss["zipFileName"]) as z:
        env = qc.strict_loads(z.read(f"{iss['deliveryId']}/quota.json"))
    site = Site(tmp_path / "site", passphrase="correct horse battery", hardware=lambda _s: ["VDIE-1", "VDIE-2"])
    site.install_quota(env, [qc.spki_b64(repo.root_key)])
    assert site.status()["maxDevices"] == 500
