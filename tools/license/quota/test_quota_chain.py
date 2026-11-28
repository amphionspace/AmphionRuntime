"""额度证书链：正常流程与攻击矩阵。全部使用临时密钥，不读取 .secure 下任何文件。"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quota_chain as qc  # noqa: E402
from device_sim import SimDevice  # noqa: E402
from site_issuer import Site  # noqa: E402
from vendor_quota import issue_quota  # noqa: E402

SALT = "DQ-TEST-QUOTA-SALT-0001"
PASS = "correct horse battery staple"
TODAY = "2026-11-27"
HW = ["VDIE-AAAA-0001", "VDIE-AAAA-0002"]


class Env:
    def __init__(self, tmp: Path, max_devices=3, reassign_budget=0, hw=None, **quota_kw):
        self.tmp = tmp
        self.root = qc.generate_key()
        self.roots = [qc.spki_b64(self.root)]
        self.hw = list(hw or HW)
        self.site = Site(tmp / "site", passphrase=PASS, hardware=lambda _s: list(self.hw),
                         witness=tmp / "witness.json")
        enroll = self.site.init("Dingqiao", "TEST_FIXED_V1", TODAY)
        kw = dict(quota_id="Q-DQ-20261127-001", project_id="DQ-EDGE", max_devices=max_devices,
                  features=["ASR"], issued_at=TODAY, issue_not_after="2027-06-30",
                  license_expires_at="", sdk_major=1, maintenance_until="", device_id_salt_id=SALT,
                  reassign_budget=reassign_budget, allow_test_hardware=True)
        kw.update(quota_kw)
        self.quota_env = issue_quota(self.root, enroll, **kw)
        self.site.install_quota(self.quota_env, self.roots)

    def activate(self, dev: SimDevice, today=TODAY) -> str:
        return self.site.activate(dev.activation_request(SALT, today), today)

    def verify(self, text: str, dev: SimDevice, **kw) -> qc.ChainResult:
        return qc.verify_chain(text, self.roots, dev.context(kw.pop("today", TODAY), **kw))

    def site_key(self):
        return serialization.load_pem_private_key(self.site.key_path.read_bytes(), PASS.encode())

    def forge_device(self, base_text: str, **changes) -> str:
        """模拟签发点私钥被提取、签发工具被改：直接用签发点私钥签任意设备授权。"""
        top = json.loads(base_text)
        claims = json.loads(qc.b64d(top["device"]["payload_b64"]))
        claims.update(changes)
        claims["licenseId"] = f"DL-{uuid.uuid4().hex[:20].upper()}"
        return qc.chain_text(top["quota"], qc.sign_envelope(self.site_key(), claims))


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def code(fn, *a, **kw) -> str:
    with pytest.raises(qc.ChainError) as ei:
        fn(*a, **kw)
    return ei.value.code


# ------------------------------------------------------------------ 正常流程

def test_happy_path_counts_and_verifies(env):
    devs = [SimDevice(f"SN{i:04d}ABCD") for i in range(3)]
    for i, d in enumerate(devs, 1):
        r = env.verify(env.activate(d), d)
        assert r.device["seq"] == i
    s = env.site.status()
    assert (s["activeDevices"], s["freeSeats"]) == (3, 0)


def test_quota_exhausted(env):
    for i in range(3):
        env.activate(SimDevice(f"SN{i:04d}ABCD"))
    assert code(env.activate, SimDevice("SN9999ABCD")) == "QUOTA_EXHAUSTED"


def test_same_device_resubmit_is_idempotent(env):
    d = SimDevice("SN0001ABCD")
    a, b = env.activate(d), env.activate(d)
    assert a == b and env.site.status()["seatsUsed"] == 1


def test_factory_reset_reissues_same_seat(env):
    d = SimDevice("SN0001ABCD")
    old = env.activate(d)
    d.reset_key()
    assert code(env.verify, old, d) == "DEVICE_KEY_MISMATCH"   # 旧授权随旧密钥失效
    new = env.activate(d)
    assert env.verify(new, d).device["seq"] == 1
    assert env.site.status()["seatsUsed"] == 1


# ------------------------------------------------------------------ 设备端：伪造与越权

def test_forged_quota_by_customer_root(env, tmp_path):
    other = Env(tmp_path / "other", max_devices=1000)
    d = SimDevice("SN0001ABCD")
    text = other.activate(d)
    assert code(env.verify, text, d) == "QUOTA_SIGNATURE_INVALID"   # 客户自建根签的额度证书不被信任


def test_tampered_max_devices(env):
    d = SimDevice("SN0001ABCD")
    top = json.loads(env.activate(d))
    q = json.loads(qc.b64d(top["quota"]["payload_b64"]))
    q["maxDevices"] = 100000
    top["quota"]["payload_b64"] = qc.b64e(qc.canonical_bytes(q))
    assert code(env.verify, json.dumps(top), d) == "QUOTA_SIGNATURE_INVALID"


def test_patched_site_seq_over_quota_rejected_on_device(env):
    base = env.activate(SimDevice("SN0001ABCD"))
    d = SimDevice("SN0004ABCD")
    forged = env.forge_device(base, seq=4, snHash=qc.device_sn_hash(d.serial, SALT),
                              devicePublicKeySha256=qc.key_id(qc.spki_b64(d.key)))
    assert code(env.verify, forged, d) == "SEQ_OUT_OF_RANGE"
    assert code(env.verify, env.forge_device(base, seq=0), d) == "SEQ_OUT_OF_RANGE"


def test_patched_site_feature_and_expiry_escalation(env):
    d = SimDevice("SN0001ABCD")
    base = env.activate(d)
    assert code(env.verify, env.forge_device(base, features=["ASR", "TTS"]), d) == "FEATURE_ESCALATION"
    assert code(env.verify, env.forge_device(base, issuedAt="2027-07-01"), d) == "ISSUE_WINDOW"


def test_expiry_cannot_exceed_quota(tmp_path):
    e = Env(tmp_path, license_expires_at="2027-12-31")
    d = SimDevice("SN0001ABCD")
    base = e.activate(d)
    assert e.verify(base, d)
    assert code(e.verify, e.forge_device(base, licenseExpiresAt=""), d) == "EXPIRY_ESCALATION"
    assert code(e.verify, e.forge_device(base, licenseExpiresAt="2028-01-01"), d) == "EXPIRY_ESCALATION"
    assert code(e.verify, base, d, today="2028-01-01") == "EXPIRED"


def test_device_license_signed_by_other_site(env, tmp_path):
    other = Env(tmp_path / "other")
    d = SimDevice("SN0001ABCD")
    mine = json.loads(env.activate(d))
    theirs = json.loads(other.activate(d))
    mixed = qc.chain_text(mine["quota"], theirs["device"])
    assert code(env.verify, mixed, d) == "DEVICE_SIGNATURE_INVALID"


def test_device_license_bound_to_its_quota(tmp_path):
    """同一签发点、同一根：拿 A 额度的设备授权配 B 额度证书（B 数量更大）也不行。"""
    e = Env(tmp_path)
    d = SimDevice("SN0001ABCD")
    top = json.loads(e.activate(d))
    q = json.loads(qc.b64d(top["quota"]["payload_b64"]))
    q["quotaId"], q["maxDevices"] = "Q-DQ-20261127-002", 500
    bigger = qc.sign_envelope(e.root, q)
    assert code(e.verify, qc.chain_text(bigger, top["device"]), d) == "QUOTA_MISMATCH"


def test_license_copied_to_other_sn(env):
    a, b = SimDevice("SN0001ABCD"), SimDevice("SN0002ABCD")
    assert code(env.verify, env.activate(a), b) == "DEVICE_MISMATCH"


def test_license_copied_to_clone_with_same_sn(env):
    """伪造 SN 的克隆机/模拟器拿不到原设备 HUKS 私钥。"""
    real = SimDevice("SN0001ABCD")
    text = env.activate(real)
    clone = SimDevice("SN0001ABCD")
    assert code(env.verify, text, clone) == "DEVICE_KEY_MISMATCH"


def test_replayed_key_proof_without_private_key(env):
    real = SimDevice("SN0001ABCD")
    text = env.activate(real)
    recorded = real.prove(b"old-challenge")
    clone = SimDevice("SN0001ABCD")
    clone.prove = lambda _c: recorded   # 重放旧挑战签名
    assert code(env.verify, text, clone) == "DEVICE_KEY_MISMATCH"


def test_type_confusion_log_entry_as_device_license(env):
    d = SimDevice("SN0001ABCD")
    top = json.loads(env.activate(d))
    log0 = json.loads(env.site.log_path.read_text().splitlines()[0])
    assert code(env.verify, qc.chain_text(top["quota"], log0), d) == "TYPE_MISMATCH"


def test_duplicate_json_keys_rejected(env):
    d = SimDevice("SN0001ABCD")
    top = json.loads(env.activate(d))
    raw = qc.b64d(top["device"]["payload_b64"]).decode()
    dup = raw[:-1] + ',"seq":1}'
    payload = dup.encode()   # 签发点签了一份带重复键的 payload：不同解析器可能读出不同 seq
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    top["device"] = {"alg": qc.ALG, "payload_b64": qc.b64e(payload),
                     "sig_b64": qc.b64e(env.site_key().sign(payload, ec.ECDSA(hashes.SHA256())))}
    assert code(env.verify, json.dumps(top), d) == "MALFORMED"


def test_unknown_fields_and_legacy_verifier(env):
    d = SimDevice("SN0001ABCD")
    top = json.loads(env.activate(d))
    top["payload_b64"] = top["device"]["payload_b64"]  # 顶层夹带：链校验拒绝
    assert code(env.verify, json.dumps(top), d) == "MALFORMED"
    # 旧 SDK 只认顶层 payload_b64：链文件对它是 malformed，失败关闭（见 test_legacy_verifier_fails_closed）。


def test_legacy_verifier_fails_closed(env):
    """旧 SDK / 旧校验工具拿到链文件：顶层没有 payload_b64，必须报错而不是放行。"""
    import subprocess
    text = env.activate(SimDevice("SN0001ABCD"))
    lic = env.tmp / "chain.lic"
    lic.write_text(text)
    tool = Path(__file__).resolve().parents[1] / "verify_license.py"
    r = subprocess.run([sys.executable, "-I", str(tool), "--license", str(lic), "--public-key-b64", env.roots[0],
                        "--device-id", "SN0001ABCD"], capture_output=True, text=True)
    assert r.returncode != 0 and "PASS" not in r.stdout.upper()


def test_feature_sdk_and_bundle_policy(tmp_path):
    e = Env(tmp_path, sdk_major=1, maintenance_until="2027-03-31", bundle_names=["com.dingqiao.police"])
    d = SimDevice("SN0001ABCD", bundle="com.dingqiao.police")
    text = e.activate(d)
    assert code(e.verify, text, d, feature="TTS") == "FEATURE_MISSING"
    assert code(e.verify, text, d, sdk_major=2) == "SDK_MAJOR_MISMATCH"
    assert code(e.verify, text, d, sdk_release_date="2027-04-01") == "MAINTENANCE_EXPIRED"
    assert code(e.verify, text, d, bundle="com.other.app") == "APP_MISMATCH"
    assert code(e.activate, SimDevice("SN0002ABCD", bundle="com.other.app")) == "APP_MISMATCH"


# ------------------------------------------------------------------ 签发点：软控制

def test_activation_request_pop(env):
    d, attacker = SimDevice("SN0001ABCD"), SimDevice("SN0001ABCD")
    req = d.activation_request(SALT, TODAY)
    claims = json.loads(qc.b64d(req["payload_b64"]))
    claims["devicePublicKey"] = qc.spki_b64(attacker.key)   # 换公钥但签名还是原设备的
    req["payload_b64"] = qc.b64e(qc.canonical_bytes(claims))
    assert code(env.site.activate, req, TODAY) == "REQUEST_POP_INVALID"


def test_site_hardware_binding(env):
    env.hw[:] = ["VDIE-OTHER-0009"]   # 签发点目录整份拷到别的机器
    assert code(env.activate, SimDevice("SN0001ABCD")) == "HARDWARE_MISMATCH"
    env.hw[:] = ["VDIE-AAAA-0002", "VDIE-NEW-0003"]   # 换掉一张卡仍可用（minHardwarePresent=1）
    env.activate(SimDevice("SN0001ABCD"))


def test_site_key_needs_passphrase(env):
    s = Site(env.site.root, passphrase="wrong passphrase!!", hardware=lambda _s: HW)
    assert code(s.activate, SimDevice("SN0001ABCD").activation_request(SALT, TODAY), TODAY) == "SITE_KEY_LOCKED"
    assert b"ENCRYPTED" in env.site.key_path.read_bytes()
    assert oct(env.site.key_path.stat().st_mode & 0o777) == "0o600"


def test_issue_window(env):
    assert code(env.activate, SimDevice("SN0001ABCD"), today="2027-07-01") == "ISSUE_WINDOW"


def test_log_tamper_detected(env):
    env.activate(SimDevice("SN0001ABCD"))
    env.activate(SimDevice("SN0002ABCD"))
    lines = env.site.log_path.read_text().splitlines()
    env.site.log_path.write_text(lines[1] + "\n")          # 删掉第一条想腾名额
    assert code(env.activate, SimDevice("SN0003ABCD")) == "LOG_CHAIN_BROKEN"
    e0 = json.loads(lines[0])
    c = json.loads(qc.b64d(e0["payload_b64"]))
    c["seq"] = 2
    e0["payload_b64"] = qc.b64e(qc.canonical_bytes(c))   # 改条目内容
    env.site.log_path.write_text(json.dumps(e0) + "\n" + lines[1] + "\n")
    assert code(env.activate, SimDevice("SN0003ABCD")) == "LOG_SIGNATURE_INVALID"


def test_whole_log_rollback_blocked_by_witness(env):
    env.activate(SimDevice("SN0001ABCD"))
    snap = env.site.log_path.read_bytes()
    env.activate(SimDevice("SN0002ABCD"))
    env.activate(SimDevice("SN0003ABCD"))
    env.site.log_path.write_bytes(snap)                     # 回滚到只用了 1 个名额的快照
    assert code(env.activate, SimDevice("SN0004ABCD")) == "ROLLBACK_SUSPECTED"


def test_rollback_with_witness_also_reverted_is_caught_by_audit(env):
    """攻击者把日志和见证文件一起回滚（整机快照恢复）：现场能签出，但对账必然发现。"""
    env.activate(SimDevice("SN0001ABCD"))
    snap_log, snap_w = env.site.log_path.read_bytes(), env.site.witness.read_bytes()
    lic2 = env.activate(SimDevice("SN0002ABCD"))
    lic3 = env.activate(SimDevice("SN0003ABCD"))
    audit_before = env.site.audit_export(TODAY)
    env.site.log_path.write_bytes(snap_log)
    env.site.witness.write_bytes(snap_w)
    lic4 = env.activate(SimDevice("SN0004ABCD"))
    lic5 = env.activate(SimDevice("SN0005ABCD"))
    # 设备端看来每张授权都合法（seq 都 ≤ 3），这是离线方案的固有边界，只能靠对账发现
    assert json.loads(qc.b64d(json.loads(lic5)["device"]["payload_b64"]))["seq"] == 3
    audit_after = env.site.audit_export(TODAY)
    rep = qc.verify_audit(audit_after, env.roots, previous_audit_text=audit_before,
                          field_licenses=[lic2, lic3, lic4, lic5])
    assert any(f.startswith("FORK") for f in rep.findings)
    assert any(f.startswith("OFF_LOG_LICENSE") for f in rep.findings)
    assert any(f.startswith("DUPLICATE_SEQ_IN_FIELD") for f in rep.findings)
    # 即使没有上次导出，只要抽检到被回滚掉的授权也能发现
    rep2 = qc.verify_audit(audit_after, env.roots, field_licenses=[lic2])
    assert any(f.startswith("OFF_LOG_LICENSE") for f in rep2.findings)


def test_off_log_forgery_detected_by_audit(env):
    base = env.activate(SimDevice("SN0001ABCD"))
    d = SimDevice("SN0002ABCD")
    forged = env.forge_device(base, seq=1, snHash=qc.device_sn_hash(d.serial, SALT),
                              devicePublicKeySha256=qc.key_id(qc.spki_b64(d.key)))
    assert env.verify(forged, d)   # 签发点私钥被盗用时设备端放行（同序号），只能靠对账
    rep = qc.verify_audit(env.site.audit_export(TODAY), env.roots, field_licenses=[base, forged])
    assert {f.split(":")[0] for f in rep.findings} == {"OFF_LOG_LICENSE", "DUPLICATE_SEQ_IN_FIELD"}


def test_clean_audit_passes(env):
    lics = [env.activate(SimDevice(f"SN{i:04d}ABCD")) for i in range(3)]
    a1 = env.site.audit_export(TODAY)
    rep = qc.verify_audit(a1, env.roots, field_licenses=lics)
    assert rep.ok and (rep.entries, rep.active_devices, rep.highest_seq) == (3, 3, 3)
    assert qc.verify_audit(env.site.audit_export(TODAY), env.roots, previous_audit_text=a1).ok


def test_audit_seal_and_root(env, tmp_path):
    env.activate(SimDevice("SN0001ABCD"))
    doc = json.loads(env.site.audit_export(TODAY))
    doc["log"] = []
    assert code(qc.verify_audit, json.dumps(doc), env.roots) == "AUDIT_SEAL_MISMATCH"
    other = Env(tmp_path / "o")
    assert code(qc.verify_audit, env.site.audit_export(TODAY), other.roots) == "QUOTA_SIGNATURE_INVALID"


# ------------------------------------------------------------------ 注销回收

def test_release_disabled_by_default(env):
    d = SimDevice("SN0001ABCD")
    text = env.activate(d)
    assert code(env.site.deactivate, d.deactivation_receipt(text, TODAY), TODAY) == "REASSIGN_DISABLED"


def test_release_with_receipt_and_budget(tmp_path):
    e = Env(tmp_path, max_devices=2, reassign_budget=1)
    a, b = SimDevice("SN0001ABCD"), SimDevice("SN0002ABCD")
    ta = e.activate(a)
    e.activate(b)
    assert code(e.activate, SimDevice("SN0003ABCD")) == "QUOTA_EXHAUSTED"
    receipt = a.deactivation_receipt(ta, TODAY)
    assert code(e.verify, ta, a) == "DEVICE_KEY_MISMATCH"   # 回执签完密钥即销毁，旧授权恢复也用不了
    assert e.site.deactivate(receipt, TODAY) == 1
    assert code(e.site.deactivate, receipt, TODAY) in ("RECEIPT_INVALID", "REASSIGN_BUDGET_EXCEEDED")  # 回执重放
    c = SimDevice("SN0003ABCD")
    assert e.verify(e.activate(c), c).device["seq"] == 1
    tb = e.activate(b)   # 同设备同密钥重复提交，原样拿回 b 的授权
    assert code(e.site.deactivate, b.deactivation_receipt(tb, TODAY), TODAY) == "REASSIGN_BUDGET_EXCEEDED"
    assert qc.verify_audit(e.site.audit_export(TODAY), e.roots).ok


def test_forged_receipt_rejected(tmp_path):
    e = Env(tmp_path, max_devices=2, reassign_budget=5)
    a = SimDevice("SN0001ABCD")
    ta = e.activate(a)
    thief = SimDevice("SN0001ABCD")
    assert code(e.site.deactivate, thief.deactivation_receipt(ta, TODAY), TODAY) == "RECEIPT_INVALID"


# ------------------------------------------------------------------ 我方签发门禁

def test_vendor_refuses_bad_enrollment(tmp_path):
    root = qc.generate_key()
    site = Site(tmp_path / "s", passphrase=PASS, hardware=lambda _s: HW)
    enroll = site.init("Dingqiao", "TEST_FIXED_V1", TODAY)
    kw = dict(quota_id="Q1", project_id="P", max_devices=3, features=["ASR"], issued_at=TODAY,
              issue_not_after="2027-01-01", license_expires_at="", sdk_major=1, maintenance_until="",
              device_id_salt_id=SALT)
    assert code(issue_quota, root, enroll, **kw) == "TEST_HARDWARE_REFUSED"
    c = json.loads(qc.b64d(enroll["payload_b64"]))
    c["customer"] = "Someone Else"
    bad = dict(enroll, payload_b64=qc.b64e(qc.canonical_bytes(c)))
    assert code(issue_quota, root, bad, allow_test_hardware=True, **kw) == "ENROLLMENT_POP_INVALID"
    assert code(issue_quota, root, enroll, allow_test_hardware=True, **dict(kw, max_devices=0)) == "MALFORMED"
    assert code(issue_quota, root, enroll, allow_test_hardware=True, **dict(kw, features=["ASR", "X"])) == "MALFORMED"


def test_quota_for_other_site_refused(env, tmp_path):
    other = Env(tmp_path / "o")
    assert code(env.site.install_quota, other.quota_env, other.roots) == "QUOTA_NOT_FOR_THIS_SITE"


def test_no_plaintext_sn_anywhere(env):
    env.activate(SimDevice("SN0001ABCD"))
    blob = b"".join(p.read_bytes() for p in env.site.root.rglob("*") if p.is_file())
    blob += env.site.audit_export(TODAY).encode()
    for f in list(env.site.lic_dir.iterdir()):
        top = json.loads(f.read_text())
        blob += qc.b64d(top["device"]["payload_b64"]) + qc.b64d(top["quota"]["payload_b64"])
    for line in env.site.log_path.read_text().splitlines():
        blob += qc.b64d(json.loads(line)["payload_b64"])
    assert b"SN0001ABCD" not in blob and b"VDIE-AAAA" not in blob


def test_batch_stops_at_quota_and_keeps_issued(env):
    reqs = [SimDevice(f"SN{i:04d}BATCH").activation_request(SALT, TODAY) for i in range(5)]
    assert code(env.site.activate_many, reqs, TODAY) == "QUOTA_EXHAUSTED"
    s = env.site.status()
    assert (s["seatsUsed"], s["logEntries"]) == (3, 3)
    assert qc.verify_audit(env.site.audit_export(TODAY), env.roots).ok
