#!/usr/bin/env python3
"""客户内网授权签发点（离线）。

部署在客户专网内的一台受控主机（推荐鼎桥私有化 ASR 服务器，硬件绑定 NPU VDie）。职责：
  init           生成签发点密钥（口令加密落盘）与入网申请 enrollment.json，交我方签额度证书
  install-quota  安装我方签发的额度证书（校验根签名、本机密钥、硬件绑定）
  activate       处理设备激活请求，按额度分配序号并签发设备授权
  deactivate     处理设备注销回执（仅额度证书允许回收时），回收序号
  audit-export   导出带签名封条的全量日志，离线带回我方对账
  status         只读查看已用/剩余额度

计数状态不单独存文件：每次启动都从签名哈希链日志重放得出，日志与状态不可能各改各的。
可选「见证文件」（另一块盘或移动介质）记录日志最高位置，日志被整体回滚到更早副本时拒绝工作。
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

sys.path.insert(0, str(Path(__file__).resolve().parent))
import quota_chain as qc  # noqa: E402

MIN_PASSPHRASE = 12
PASSPHRASE_ENV = "AMPHION_SITE_PASSPHRASE"
HardwareProvider = Callable[[str], List[str]]


# ---------------------------------------------------------------- 硬件标识

def _npu_smi(args: Sequence[str]) -> str:
    try:
        out = subprocess.run(["npu-smi", *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, check=False, timeout=5)
    except (OSError, subprocess.SubprocessError) as error:
        raise qc.ChainError("HARDWARE_UNAVAILABLE", "npu-smi") from error
    if out.returncode != 0 or len(out.stdout) > 1 << 20:
        raise qc.ChainError("HARDWARE_UNAVAILABLE", "npu-smi")
    return out.stdout.decode("utf-8", "strict")


def system_hardware(scheme: str) -> List[str]:
    """返回本机硬件标识原值（只在内存中使用，不落盘、不进日志）。"""
    if scheme == "ASCEND_NPU_VDIE_V1":
        ids = []
        for line in _npu_smi(("info", "-l")).splitlines():
            m = re.match(r"^\s*NPU ID\s*:\s*(\d+)\s*$", line)
            if not m:
                continue
            board = _npu_smi(("info", "-t", "board", "-i", m.group(1), "-c", "0"))
            vals = [l.split(":", 1)[1].strip().replace(" ", "") for l in board.splitlines()
                    if "VDie ID" in l and ":" in l]
            if len(vals) != 1:
                raise qc.ChainError("HARDWARE_UNAVAILABLE", "VDie")
            ids.append(vals[0])
        return ids
    if scheme == "LINUX_MACHINE_ID_V1":
        try:
            return [Path("/etc/machine-id").read_text("ascii").strip()]
        except OSError as error:
            raise qc.ChainError("HARDWARE_UNAVAILABLE", "machine-id") from error
    if scheme == "TEST_FIXED_V1":
        return [v for v in os.environ.get("AMPHION_TEST_HW_IDS", "").split(",") if v.strip()]
    raise qc.ChainError("MALFORMED", "hardware scheme")


# ---------------------------------------------------------------- 文件工具

def _write_private(path: Path, data: bytes) -> None:
    """原子写 + fsync，权限 0600。"""
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def _passphrase(explicit: Optional[str]) -> bytes:
    value = explicit if explicit is not None else os.environ.get(PASSPHRASE_ENV, "")
    if len(value) < MIN_PASSPHRASE:
        raise qc.ChainError("PASSPHRASE_REQUIRED", f"site key passphrase must be >= {MIN_PASSPHRASE} chars")
    return value.encode("utf-8")


class Site:
    def __init__(self, root: Path, passphrase: Optional[str] = None,
                 hardware: HardwareProvider = system_hardware,
                 witness: Optional[Path] = None) -> None:
        self.root = Path(root)
        self._pass = passphrase
        self._hardware = hardware
        self.witness = Path(witness) if witness else None

    # 路径
    key_path = property(lambda s: s.root / "site-key.pem")
    enroll_path = property(lambda s: s.root / "enrollment.json")
    quota_path = property(lambda s: s.root / "quota.json")
    log_path = property(lambda s: s.root / "log.jsonl")
    lic_dir = property(lambda s: s.root / "licenses")

    # ------------------------------------------------------------ 初始化
    def init(self, customer: str, scheme: str, today: str) -> Dict[str, str]:
        if self.root.exists() and any(self.root.iterdir()):
            raise qc.ChainError("SITE_EXISTS", "site directory is not empty")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        site_id = f"SITE-{uuid.uuid4().hex[:16].upper()}"
        key = qc.generate_key()
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.BestAvailableEncryption(_passphrase(self._pass)))
        _write_private(self.key_path, pem)
        claims = {
            "type": qc.T_SITE_ENROLL, "siteId": site_id, "customer": customer,
            "sitePublicKey": qc.spki_b64(key),
            "hardware": {"scheme": scheme,
                         "hashes": qc.hardware_binding_hash(scheme, site_id, self._hardware(scheme))},
            "createdAt": today, "nonce": uuid.uuid4().hex,
        }
        qc.validate_enrollment(claims)
        env = qc.sign_envelope(key, claims)  # 自签 = 持有私钥证明
        _write_private(self.enroll_path, (json.dumps(env, indent=1) + "\n").encode())
        self.lic_dir.mkdir(mode=0o700)
        _write_private(self.log_path, b"")
        return env

    def _key(self) -> ec.EllipticCurvePrivateKey:
        try:
            key = serialization.load_pem_private_key(self.key_path.read_bytes(), _passphrase(self._pass))
        except (ValueError, TypeError) as error:
            raise qc.ChainError("SITE_KEY_LOCKED", "wrong passphrase or damaged key") from error
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise qc.ChainError("SITE_KEY_LOCKED", "not an EC key")
        return key

    # ------------------------------------------------------------ 额度证书
    def install_quota(self, quota_env: Dict[str, str], trusted_roots: Sequence[str]) -> Dict:
        _, quota = qc.open_envelope(quota_env, trusted_roots, qc.T_QUOTA, "QUOTA_SIGNATURE_INVALID")
        qc.validate_quota(quota)
        enroll_bytes = qc.b64d(json.loads(self.enroll_path.read_text())["payload_b64"])
        if quota["enrollmentSha256"] != qc.sha256_hex(enroll_bytes):
            raise qc.ChainError("QUOTA_NOT_FOR_THIS_SITE", "enrollment digest")
        if quota["site"]["publicKey"] != qc.spki_b64(self._key()):
            raise qc.ChainError("QUOTA_NOT_FOR_THIS_SITE", "site key")
        if self.quota_path.exists():
            raise qc.ChainError("QUOTA_EXISTS", "one site directory holds one quota; use a new site for a new batch")
        self._check_hardware(quota)
        _write_private(self.quota_path, (json.dumps({"quota": quota_env, "trustedRoots": list(trusted_roots)},
                                                    indent=1) + "\n").encode())
        return quota

    def _load_quota(self):
        doc = json.loads(self.quota_path.read_text())
        q_bytes, quota = qc.open_envelope(doc["quota"], doc["trustedRoots"], qc.T_QUOTA, "QUOTA_SIGNATURE_INVALID")
        qc.validate_quota(quota)
        return doc["quota"], quota, qc.sha256_hex(q_bytes)

    def _check_hardware(self, quota: Dict) -> None:
        site = quota["site"]
        present = set(qc.hardware_binding_hash(site["hardware"]["scheme"], site["siteId"],
                                               self._hardware(site["hardware"]["scheme"])))
        if len(present & set(site["hardware"]["hashes"])) < site["minHardwarePresent"]:
            raise qc.ChainError("HARDWARE_MISMATCH", "site is not running on the bound hardware")

    # ------------------------------------------------------------ 日志
    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        fd = os.open(self.root / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read_log(self) -> List[Dict[str, str]]:
        out = []
        for n, line in enumerate(self.log_path.read_text("utf-8").splitlines()):
            if not line.strip():
                raise qc.ChainError("LOG_INVALID", f"blank line {n}")
            out.append(qc.strict_loads(line))
        return out

    def _replay(self):
        quota_env, quota, q_sha = self._load_quota()
        lines = self._read_log()
        rep = qc.replay_log(lines, quota, q_sha)
        self._check_witness(rep)
        return quota_env, quota, q_sha, lines, rep

    def _check_witness(self, rep: qc.LogReplay) -> None:
        if self.witness is None or not self.witness.exists():
            return
        w = qc.strict_loads(self.witness.read_bytes())
        n, head = w.get("entries"), w.get("head")
        if type(n) is not int or n > rep.count or (n and rep.entry_hashes[n - 1] != head):
            raise qc.ChainError("ROLLBACK_SUSPECTED", "log is older than witness record")

    def _append(self, key, quota, q_sha, rep: qc.LogReplay, event: str, seq: int, sn: str,
                dev_key_sha: str, lic_sha: str, receipt_sha: str, today: str) -> None:
        entry = {"type": qc.T_LOG, "quotaId": quota["quotaId"], "quotaSha256": q_sha, "index": rep.count,
                 "prev": rep.head, "at": today, "event": event, "seq": seq, "snHash": sn,
                 "devicePublicKeySha256": dev_key_sha, "licenseSha256": lic_sha, "receiptSha256": receipt_sha}
        env = qc.sign_envelope(key, entry)
        qc.apply_log_entry(rep, env, quota, q_sha)  # 写盘前按同一规则自检，并增量更新内存状态
        line = json.dumps(env, sort_keys=True, separators=(",", ":")) + "\n"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
        if self.witness is not None:
            head = qc.sha256_hex(qc.b64d(env["payload_b64"]))
            _write_private(self.witness, json.dumps({"quotaId": quota["quotaId"], "entries": rep.count,
                                                     "head": head}).encode())

    # ------------------------------------------------------------ 激活
    def activate(self, request_env: Dict[str, str], today: str) -> str:
        return self.activate_many([request_env], today)[0]

    def activate_many(self, request_envs: Sequence[Dict[str, str]], today: str) -> List[str]:
        """批量激活（工厂预装）：解锁一次、重放一次，逐条在内存中增量校验与入账。任一条失败即停止，已入账的保留。"""
        reqs = [self._check_request(r) for r in request_envs]
        with self._locked():
            key = self._key()
            quota_env, quota, q_sha, _, rep = self._replay()
            self._check_hardware(quota)
            return [self._issue_one(key, quota_env, quota, q_sha, rep, req, today) for req in reqs]

    @staticmethod
    def _check_request(request_env: Dict[str, str]) -> Dict:
        # 激活请求必须由请求里声明的设备公钥签名（持有证明），防止替他人设备伪造请求。
        try:
            claimed = qc.strict_loads(qc.b64d(request_env["payload_b64"]))
            device_pub = claimed["devicePublicKey"]
        except (KeyError, TypeError) as error:
            raise qc.ChainError("MALFORMED", "activation request") from error
        _, req = qc.open_envelope(request_env, [device_pub], qc.T_ACTIVATION, "REQUEST_POP_INVALID")
        return qc.validate_activation(req)

    def _issue_one(self, key, quota_env, quota, q_sha, rep, req, today) -> str:
        device_pub = req["devicePublicKey"]
        if not quota["issuedAt"] <= today <= quota["issueNotAfter"]:
            raise qc.ChainError("ISSUE_WINDOW", "quota issuance window closed or not yet open")
        if req["deviceIdSaltId"] != quota["deviceIdSaltId"]:
            raise qc.ChainError("QUOTA_MISMATCH", "salt")
        if quota["applicationBindingMode"] == "allowlist" and req["bundleName"] not in (
                quota["bundleNames"] + quota["applicationIds"]):
            raise qc.ChainError("APP_MISMATCH", "bundle not allowed by quota")
        dev_key_sha = qc.key_id(device_pub)
        sn = req["snHash"]
        cur = rep.active.get(sn)
        if cur is not None and cur["devicePublicKeySha256"] == dev_key_sha:
            # 重复提交同一设备同一密钥：原样返回，不占新名额。
            return (self.lic_dir / f"{cur['licenseSha256']}.lic").read_text("utf-8")
        if cur is not None:
            event, seq = "reissue", cur["seq"]   # 同 SN 换了设备密钥（恢复出厂/重装）：沿用原序号
        elif rep.free_seqs:
            event, seq = "issue", rep.free_seqs[0]
        elif rep.next_seq <= quota["maxDevices"]:
            event, seq = "issue", rep.next_seq
        else:
            raise qc.ChainError("QUOTA_EXHAUSTED", f"all {quota['maxDevices']} seats used")
        claims = {"type": qc.T_DEVICE, "licenseId": f"DL-{uuid.uuid4().hex[:20].upper()}",
                  "quotaId": quota["quotaId"], "quotaSha256": q_sha, "siteKeyId": quota["site"]["keyId"],
                  "seq": seq, "snHash": sn, "deviceIdSaltId": quota["deviceIdSaltId"],
                  "devicePublicKeySha256": dev_key_sha, "features": list(quota["features"]),
                  "licenseExpiresAt": quota["licenseExpiresAt"], "issuedAt": today,
                  "logIndex": rep.count, "logPrevHash": rep.head}
        qc.validate_device(claims)
        dev_env = qc.sign_envelope(key, claims)
        lic_sha = qc.sha256_hex(qc.b64d(dev_env["payload_b64"]))
        text = qc.chain_text(quota_env, dev_env)
        # 先落授权文件，再写日志：崩溃时最多留下一个未入账、也未交付的文件，不会出现已入账却丢失的名额。
        _write_private(self.lic_dir / f"{lic_sha}.lic", text.encode("utf-8"))
        self._append(key, quota, q_sha, rep, event, seq, sn, dev_key_sha, lic_sha, "", today)
        return text

    # ------------------------------------------------------------ 注销回收
    def deactivate(self, receipt_env: Dict[str, str], today: str) -> int:
        try:
            claimed = qc.strict_loads(qc.b64d(receipt_env["payload_b64"]))
            device_pub = claimed["devicePublicKey"]
        except (KeyError, TypeError) as error:
            raise qc.ChainError("MALFORMED", "receipt") from error
        r_bytes, rc = qc.open_envelope(receipt_env, [device_pub], qc.T_DEACT, "RECEIPT_INVALID")
        qc._exact_keys(rc, ("type", "quotaId", "seq", "snHash", "licenseSha256", "devicePublicKey",
                            "createdAt", "nonce"), "receipt")
        with self._locked():
            key = self._key()
            _, quota, q_sha, _, rep = self._replay()
            self._check_hardware(quota)
            if quota["reassignment"]["mode"] != "receipt":
                raise qc.ChainError("REASSIGN_DISABLED", "quota does not allow seat release")
            if rep.releases >= quota["reassignment"]["budget"]:
                raise qc.ChainError("REASSIGN_BUDGET_EXCEEDED", "release budget used up")
            cur = rep.active.get(rc["snHash"])
            if (cur is None or rc["quotaId"] != quota["quotaId"] or cur["seq"] != rc["seq"]
                    or cur["licenseSha256"] != rc["licenseSha256"]
                    or cur["devicePublicKeySha256"] != qc.key_id(device_pub)):
                raise qc.ChainError("RECEIPT_INVALID", "receipt does not match the active license")
            self._append(key, quota, q_sha, rep, "release", rc["seq"], rc["snHash"], cur["devicePublicKeySha256"],
                         "", qc.sha256_hex(r_bytes), today)
            return rc["seq"]

    # ------------------------------------------------------------ 审计与状态
    def audit_export(self, today: str) -> str:
        with self._locked():
            key = self._key()
            quota_env, quota, _, lines, rep = self._replay()
            seal = qc.sign_envelope(key, {"type": qc.T_AUDIT, "quotaId": quota["quotaId"], "entries": rep.count,
                                          "head": rep.head, "exportedAt": today})
            return json.dumps({"format": qc.T_AUDIT, "quota": quota_env, "log": lines, "seal": seal},
                              sort_keys=True, indent=1) + "\n"

    def status(self) -> Dict:
        _, quota, _, _, rep = self._replay()
        return {"quotaId": quota["quotaId"], "maxDevices": quota["maxDevices"], "activeDevices": len(rep.active),
                "seatsUsed": rep.next_seq - 1 - len(rep.free_seqs), "freeSeats": quota["maxDevices"] - (
                    rep.next_seq - 1 - len(rep.free_seqs)),
                "releases": rep.releases, "releaseBudget": quota["reassignment"]["budget"],
                "issueNotAfter": quota["issueNotAfter"], "logEntries": rep.count, "logHead": rep.head}


# ---------------------------------------------------------------- CLI

def _main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site-dir", required=True, type=Path)
    ap.add_argument("--witness", type=Path, help="另一块盘/移动介质上的见证文件路径（建议）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--customer", required=True)
    p.add_argument("--hardware-scheme", default="ASCEND_NPU_VDIE_V1", choices=qc.HW_SCHEMES)
    p = sub.add_parser("install-quota"); p.add_argument("--quota", required=True, type=Path)
    p.add_argument("--trusted-root", action="append", required=True, help="根公钥 SPKI base64，可多次")
    p = sub.add_parser("activate"); p.add_argument("--request", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p = sub.add_parser("activate-batch"); p.add_argument("--request-dir", required=True, type=Path)
    p.add_argument("--out-dir", required=True, type=Path)
    p = sub.add_parser("deactivate"); p.add_argument("--receipt", required=True, type=Path)
    p = sub.add_parser("audit-export"); p.add_argument("--out", required=True, type=Path)
    sub.add_parser("status")
    a = ap.parse_args(argv)
    site = Site(a.site_dir, witness=a.witness)
    today = qc.today_utc()
    try:
        if a.cmd == "init":
            site.init(a.customer, a.hardware_scheme, today)
            print(f"enrollment written: {site.enroll_path}（发给我方签额度证书；私钥不离开本机）")
        elif a.cmd == "install-quota":
            q = site.install_quota(qc.strict_loads(a.quota.read_bytes()), a.trusted_root)
            print(f"quota installed: {q['quotaId']} maxDevices={q['maxDevices']}")
        elif a.cmd == "activate":
            text = site.activate(qc.strict_loads(a.request.read_bytes()), today)
            _write_private(a.out, text.encode("utf-8"))
            print(f"device license written: {a.out}")
        elif a.cmd == "activate-batch":
            reqs = sorted(a.request_dir.glob("*.json"))
            texts = site.activate_many([qc.strict_loads(p.read_bytes()) for p in reqs], today)
            a.out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            for p, text in zip(reqs, texts):
                _write_private(a.out_dir / (p.stem + ".lic"), text.encode("utf-8"))
            print(f"{len(texts)} device licenses written: {a.out_dir}")
        elif a.cmd == "deactivate":
            print(f"seat released: seq={site.deactivate(qc.strict_loads(a.receipt.read_bytes()), today)}")
        elif a.cmd == "audit-export":
            _write_private(a.out, site.audit_export(today).encode("utf-8"))
            print(f"audit written: {a.out}")
        else:
            print(json.dumps(site.status(), ensure_ascii=False, indent=1))
    except qc.ChainError as error:
        print(f"ERROR {error.code}: {error.detail}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
