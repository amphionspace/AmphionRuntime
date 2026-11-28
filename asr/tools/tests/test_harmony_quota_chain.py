"""鸿蒙 QuotaChain.ts 与 Python 签发端互测：同一份 fixtures（安卓 JVM 单测也用它），node:crypto 充当 cryptoFramework/HUKS。"""
import base64
import json
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/QuotaChain.ts"
QUOTA_TOOLS = REPO_ROOT / "tools/license/quota"
FIXTURES = REPO_ROOT / "asr/android/sdk/src/test/resources/quota-chain/fixtures.json"

PRELUDE = """
import assert from 'node:assert/strict';
import * as nc from 'node:crypto';
import { readFileSync } from 'node:fs';
import * as qc from %(core)s;
const crypto = {
  b64decode: (t) => new Uint8Array(Buffer.from(t, 'base64')),
  b64encode: (b) => Buffer.from(b).toString('base64'),
  utf8Encode: (t) => new Uint8Array(Buffer.from(t, 'utf8')),
  utf8Decode: (b) => new TextDecoder('utf-8', { fatal: true }).decode(b),
  sha256: async (b) => new Uint8Array(nc.createHash('sha256').update(b).digest()),
  isP256: async (spki) => nc.createPublicKey({ key: Buffer.from(spki), format: 'der', type: 'spki' })
    .asymmetricKeyDetails.namedCurve === 'prime256v1',
  ecdsaVerify: async (spki, data, sig) => nc.verify('sha256', data,
    nc.createPublicKey({ key: Buffer.from(spki), format: 'der', type: 'spki' }), sig),
  randomBytes: (n) => new Uint8Array(nc.randomBytes(n)),
};
function softKey(pkcs8, spki) {
  const priv = nc.createPrivateKey({ key: Buffer.from(pkcs8, 'base64'), format: 'der', type: 'pkcs8' });
  return { publicKeySpki: async () => new Uint8Array(Buffer.from(spki, 'base64')),
           sign: async (d) => new Uint8Array(nc.sign('sha256', d, priv)) };
}
function newKey() {
  const kp = nc.generateKeyPairSync('ec', { namedCurve: 'prime256v1' });
  return softKey(kp.privateKey.export({ format: 'der', type: 'pkcs8' }).toString('base64'),
                 kp.publicKey.export({ format: 'der', type: 'spki' }).toString('base64'));
}
async function code(p) { try { return { code: 'OK', value: await p }; } catch (e) {
  if (!(e instanceof qc.QuotaChainError)) throw e; return { code: e.code }; } }
"""


class HarmonyQuotaChainTest(unittest.TestCase):
    def run_node(self, body: str) -> str:
        script = PRELUDE % {"core": repr(CORE.as_uri())} + textwrap.dedent(body)
        out = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "--input-type=module", "-e", script],
                             check=True, cwd=REPO_ROOT, capture_output=True, text=True)
        return out.stdout

    def test_python_fixtures_verify_identically(self) -> None:
        out = self.run_node(f"""
            const doc = JSON.parse(readFileSync({json.dumps(str(FIXTURES))}, 'utf8'));
            const bad = [];
            for (const c of doc.cases) {{
              const ctx = {{ serial: c.serial, bundleName: c.bundle, sdkMajor: c.sdkMajor, sdkReleaseDate: c.sdkReleaseDate,
                requiredFeature: c.feature, today: c.today, deviceKey: softKey(c.deviceKeyPkcs8, c.deviceKeySpki) }};
              const r = await code(qc.verifyQuotaChain(c.license, doc.trustedRoots, ctx, crypto));
              if (r.code !== c.expect) bad.push(`${{c.name}}: python=${{c.expect}} harmony=${{r.code}}`);
              if (r.code === 'OK' && c.expectSeq !== undefined && r.value.seq !== c.expectSeq) bad.push(`${{c.name}} seq`);
            }}
            assert.deepEqual(bad, []);
            console.log(doc.cases.length);
        """)
        self.assertGreaterEqual(int(out.strip()), 15)

    def test_unarmed_refuses_chain(self) -> None:
        self.run_node("""
            const ctx = { serial: 'SN0001', bundleName: '', sdkMajor: 1, sdkReleaseDate: '', requiredFeature: 'ASR',
              today: '2026-11-27', deviceKey: newKey() };
            assert.equal((await code(qc.verifyQuotaChain('{}', '', ctx, crypto))).code, 'NOT_ARMED');
        """)

    def test_strict_json_rejects_ambiguity(self) -> None:
        self.run_node(r"""
            for (const bad of ['{"a":1,"a":2}', '{"a":1.5}', '{"a":NaN}', '{"a":1} x', '{"a":01}', '{"a":1e3}',
                               '{"a":9007199254740993}', '{"a":"\u0001"}', '[' .repeat(40)]) {
              assert.throws(() => qc.strictParse(bad), qc.QuotaChainError, bad);
            }
            assert.deepEqual(qc.strictParse('{"k":[1,"中文\\n"]}'), { k: [1, '中文\n'] });
            const p = qc.strictParse('{"__proto__":{"x":1}}');
            assert.equal(Object.getPrototypeOf(p), Object.prototype);
            assert.deepEqual(Object.keys(p), ['__proto__']);
        """)

    def test_is_chain_and_clock_watermark(self) -> None:
        self.run_node("""
            assert.equal(qc.isQuotaChain('{"format":"amphion.quota-chain.v1"}'), true);
            assert.equal(qc.isQuotaChain('{"payload_b64":"x","sig_b64":"y","alg":"SHA256withECDSA"}'), false);
            assert.equal(qc.isQuotaChain('{"format":"amphion.quota-chain.v1","format":"x"}'), false);
            assert.equal(qc.effectiveToday('2026-01-01', '2026-11-27'), '2026-11-27');
            assert.equal(qc.effectiveToday('2026-12-01', '2026-11-27'), '2026-12-01');
            assert.equal(qc.effectiveToday('2026-12-01', ''), '2026-12-01');
        """)

    def test_rolled_back_clock_cannot_revive_expired_license(self) -> None:
        self.run_node(f"""
            const doc = JSON.parse(readFileSync({json.dumps(str(FIXTURES))}, 'utf8'));
            const c = doc.cases.find((x) => x.name === 'expired');
            const ctx = (today) => ({{ serial: c.serial, bundleName: c.bundle, sdkMajor: c.sdkMajor,
              sdkReleaseDate: c.sdkReleaseDate, requiredFeature: c.feature, today,
              deviceKey: softKey(c.deviceKeyPkcs8, c.deviceKeySpki) }});
            // 设备时钟被调回到很久以前，但水位记着已见过的日期
            const today = qc.effectiveToday('2020-01-01', c.today);
            assert.equal((await code(qc.verifyQuotaChain(c.license, doc.trustedRoots, ctx(today), crypto))).code, 'EXPIRED');
        """)

    def test_round_trip_with_python_site_issuer(self) -> None:
        """鸿蒙端生成激活请求 → Python 签发点签授权 → 鸿蒙端校验 → 鸿蒙端签注销回执 → 签发点回收序号。"""
        import tempfile
        sys.path.insert(0, str(QUOTA_TOOLS))
        import quota_chain as qc
        from cryptography.hazmat.primitives import serialization
        from test_quota_chain import SALT, TODAY, Env

        with tempfile.TemporaryDirectory() as tmp:
            env = Env(Path(tmp), max_devices=1, reassign_budget=1)
            key = qc.generate_key()
            pkcs8 = base64.b64encode(key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                                       serialization.NoEncryption())).decode()
            spki = qc.spki_b64(key)
            prelude = f"""
                const key = softKey({pkcs8!r}, {spki!r});
                const ctx = {{ serial: 'hm0001xyz', bundleName: 'com.dingqiao.police', sdkMajor: 1,
                  sdkReleaseDate: '', requiredFeature: 'ASR', today: {TODAY!r}, deviceKey: key }};
            """
            request = self.run_node(prelude + f"""
                console.log(await qc.buildActivationRequest(ctx.serial, {SALT!r}, 'harmony_arm64', ctx.bundleName,
                  {TODAY!r}, key, crypto));
            """)
            license_text = env.site.activate(qc.strict_loads(request), TODAY)
            self.assertEqual(env.site.status()["activeDevices"], 1)
            Path(tmp, "lic.json").write_text(license_text)
            receipt = self.run_node(prelude + f"""
                const text = readFileSync({json.dumps(str(Path(tmp, "lic.json")))}, 'utf8');
                const r = await code(qc.verifyQuotaChain(text, {",".join(env.roots)!r}, ctx, crypto));
                assert.equal(r.code, 'OK');
                assert.equal(r.value.seq, 1);
                const other = await code(qc.verifyQuotaChain(text, {",".join(env.roots)!r},
                  {{ ...ctx, deviceKey: newKey() }}, crypto));
                assert.equal(other.code, 'DEVICE_KEY_MISMATCH');
                console.log(await qc.buildDeactivationReceipt(text, {TODAY!r}, key, crypto));
            """)
            self.assertEqual(env.site.deactivate(qc.strict_loads(receipt), TODAY), 1)
            self.assertEqual(env.site.status()["freeSeats"], 1)


if __name__ == "__main__":
    unittest.main()
