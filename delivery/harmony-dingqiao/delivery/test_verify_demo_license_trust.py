from pathlib import Path
import os
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("verify_demo_inputs.sh")


class VerifyDemoLicenseTrustTest(unittest.TestCase):
    def test_private_key_and_license_must_each_belong_to_sdk_trust_set(self):
        source = SCRIPT.read_text()
        block = source.split('if [[ -s "$PRIVATE_KEY" ]]; then', 1)[1].split(
            '"$PYTHON" "$REPO_ROOT/tools/license/verify_license_device_set.py"', 1
        )[0]
        block = 'if [[ -s "$PRIVATE_KEY" ]]; then' + block
        for keys, private, signer, valid, expected in [
            ("key-a", "key-a", "key-a", "yes", True),
            ("key-a,key-b", "key-b", "key-b", "yes", True),
            ("key-b,key-a", "key-a", "key-b", "yes", True),
            ("key-a,key-b", "foreign", "key-b", "yes", False),
            ("key-a,key-b", "key-b", "foreign", "yes", False),
            ("key-a,key-b", "key-b", "key-b", "no", False),
        ]:
            with self.subTest(keys=keys, private=private, signer=signer, valid=valid):
                with tempfile.TemporaryDirectory() as directory:
                    key = Path(directory) / "private.pem"
                    key.write_text("test private key placeholder")
                    setup = '''set -euo pipefail
openssl() {
  if [[ "$1" == pkey ]]; then echo "$DERIVED_KEY"; else cat; fi
}
verify_license() {
  while [[ $# -gt 0 ]]; do
    if [[ "$1" == --public-key-b64 ]]; then
      [[ "$2" == "$LICENSE_SIGNER" && "$LICENSE_VALID" == yes ]]
      return
    fi
    shift
  done
  return 1
}
PYTHON=verify_license
REPO_ROOT=unused
LICENSE_FILE=unused
BUNDLE_NAME=unused
'''
                    env = dict(os.environ, PRIVATE_KEY=str(key), PUBLIC_KEY_B64=keys,
                               DERIVED_KEY=private, LICENSE_SIGNER=signer, LICENSE_VALID=valid)
                    result = subprocess.run(["bash", "-c", setup + block], env=env,
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode == 0, expected, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
