# Lits TTS Android License

This SDK build is armed when `AMPHION_LICENSE_PUBLIC_KEY` is set in `tts/android/gradle.properties` or passed with `-PAMPHION_LICENSE_PUBLIC_KEY=...`.

For an armed build, place the signed license file in the host app assets. The SDK AAR does not embed customer license files; the host app must package the matching license in its `assets/` directory.

```text
app/src/main/assets/amphion-license.lic
```

The demo APK may carry its own demo-only license for install testing. That license is separate from the customer license shipped for AAR integration.

The license is signed offline with the Amphion private key and is validated locally by the SDK. The private key and generated customer license files must stay out of Git.

To verify a license locally:

```bash
python tts/tools/license/verify_license.py \
  --license path/to/amphion-license.lic \
  --public-key-b64 "<AMPHION_LICENSE_PUBLIC_KEY>" \
  --application-id "<host applicationId>"
```
