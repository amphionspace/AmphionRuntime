from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]


class ReleaseDefaultsTest(unittest.TestCase):
    def test_039_changelog_limits_the_release_to_public_log_configuration(self) -> None:
        changelog = (
            REPO_ROOT / "delivery/harmony-dingqiao/docs/CHANGELOG.md"
        ).read_text(encoding="utf-8")
        notes_039 = changelog.split("## 0.3.9", 1)[1].split("\n## ", 1)[0]

        self.assertIn("setLogLevel", notes_039)
        self.assertIn("version=0.3.9", notes_039)
        self.assertIn("默认日志等级仍为 `WARN`", notes_039)
        self.assertIn("生命周期与诊断采集逻辑均未修改", notes_039)

    def test_038_changelog_distinguishes_new_work_from_037_carryover(self) -> None:
        changelog = (
            REPO_ROOT / "delivery/harmony-dingqiao/docs/CHANGELOG.md"
        ).read_text(encoding="utf-8")
        notes_038 = changelog.split("## 0.3.8", 1)[1].split("\n## ", 1)[0]

        self.assertIn("相对 0.3.7", notes_038)
        self.assertIn("0.3.7 已交付", notes_038)
        self.assertIn("不作为 0.3.8 新增修复", notes_038)
        self.assertIn("Speaker VAD 尾部时延", notes_038)
        self.assertIn("独立 Diagnostics SDK", notes_038)
        self.assertNotIn("避免交替讲话时应用闪退", notes_038)

    def test_ci_discovers_all_harmony_contracts_and_runs_finish_compat_gate_tests(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/android.yml").read_text(encoding="utf-8")

        self.assertIn(
            "python3 -m unittest discover -s asr/tools/tests -p 'test_harmony_*.py' -v",
            workflow,
        )
        self.assertIn(
            "delivery.harmony-dingqiao.delivery.test_run_finish_compat_release_gate",
            workflow,
        )

    def test_police_parity_fetches_only_frozen_police_history(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/android.yml").read_text(encoding="utf-8")
        parity = workflow.split("  police-parity:", 1)[1].split("  host-agc:", 1)[0]

        self.assertIn("fetch-depth: 1", parity)
        self.assertIn("Fetch frozen police asset source", parity)
        self.assertIn('git fetch --no-tags --depth=1 origin "$source_commit"', parity)
        self.assertNotIn("fetch-depth: 0", parity)
        self.assertIn("if: needs.changes.outputs.police == 'true'", parity)

    def test_android_native_cache_is_exact_verified_and_only_skips_native_build(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/android.yml").read_text(encoding="utf-8")
        android = workflow.split("  android-aar:", 1)[1].split("  ci-result:", 1)[0]
        native_cache = android.split("- name: Restore verified native artifacts", 1)[1].split(
            "- name: Set up Gradle", 1
        )[0]

        self.assertIn("steps.native-fingerprint.outputs.fingerprint", native_cache)
        self.assertNotIn("restore-keys:", native_cache)
        self.assertIn("steps.native-cache.outputs.cache-hit == 'true'", android)
        self.assertIn("steps.native-cache.outputs.cache-hit != 'true'", android)
        self.assertIn("android_native_cache.py verify", android)
        self.assertIn("android_native_cache.py create-manifest", android)
        self.assertIn("env.NATIVE_CACHE_MANIFEST", native_cache)
        self.assertIn("native-cache-manifest.json", workflow)
        self.assertIn('$ANDROID_HOME/cmake/${{ env.CMAKE_VERSION }}/bin', android)
        self.assertIn("asr.tools.tests.test_android_native_cache", workflow)

        native_build = android.index("bash asr/tools/04_build_android_so.sh arm64-v8a")
        gradle_build = android.index("Gradle assemble + unit test")
        self.assertLess(native_build, gradle_build)
        gradle_section = android[gradle_build:].split("- name: Verify AAR contents", 1)[0]
        self.assertNotIn("cache-hit", gradle_section)

    def test_native_cache_hit_skips_ndk_setup_but_not_gradle(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/android.yml").read_text(encoding="utf-8")
        android = workflow.split("  android-aar:", 1)[1].split("  ci-result:", 1)[0]

        sdk_setup = android.split("- name: Set up Android SDK", 1)[1].split(
            "- name: Install Android native SDK tools", 1
        )[0]
        native_setup = android.split("- name: Install Android native SDK tools", 1)[1].split(
            "- name: Set up Gradle", 1
        )[0]
        gradle_build = android.split("- name: Gradle assemble + unit test", 1)[1].split(
            "- name: Verify AAR contents", 1
        )[0]

        self.assertNotIn("ndk;${{ env.NDK_VERSION }}", sdk_setup)
        self.assertIn("steps.native-cache.outputs.cache-hit != 'true'", native_setup)
        self.assertIn('sdkmanager "ndk;${NDK_VERSION}"', native_setup)
        self.assertNotIn("steps.native-cache.outputs.cache-hit", gradle_build)

    def test_android_applies_pinned_sherpa_patches_before_cache_or_bridge_checks(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/android.yml").read_text(encoding="utf-8")
        android = workflow.split("  android-aar:", 1)[1].split("  ci-result:", 1)[0]

        apply_patches = android.index("bash asr/tools/apply_sherpa_patches.sh")
        self.assertLess(apply_patches, android.index("Compute Android native source fingerprint"))
        self.assertLess(apply_patches, android.index("Verify Kotlin bridge in sync with submodule"))
        patch_step = android.split("- name: Apply pinned sherpa-onnx patches", 1)[1].split(
            "- name: Compute Android native source fingerprint", 1
        )[0]
        self.assertNotIn("cache-hit", patch_step)

    def test_ci_prefers_official_gradle_repositories(self) -> None:
        settings = (REPO_ROOT / "asr/android/settings.gradle.kts").read_text(
            encoding="utf-8"
        )

        ci_check = 'System.getenv("CI").equals("true", ignoreCase = true)'
        self.assertEqual(settings.count(ci_check), 4)
        plugin_repositories = settings.split("pluginManagement", 1)[1].split(
            "dependencyResolutionManagement", 1
        )[0]
        dependency_repositories = settings.split(
            "dependencyResolutionManagement", 1
        )[1].split("rootProject.name", 1)[0]

        for repositories in (plugin_repositories, dependency_repositories):
            official = repositories.index(f"if ({ci_check})")
            mirror = repositories.index("https://maven.aliyun.com")
            self.assertLess(official, mirror)

    def test_finish_compat_release_gate_is_part_of_the_project_working_agreement(self) -> None:
        agreement = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        device_stress = (
            REPO_ROOT / "delivery/harmony-dingqiao/docs/DEVICE_STRESS.md"
        ).read_text(encoding="utf-8")

        command = "delivery/harmony-dingqiao/delivery/run_finish_compat_release_gate.py"
        self.assertIn(command, agreement)
        self.assertIn(command, device_stress)
        self.assertIn("FINISH_COMPATIBILITY_POSTMORTEM.md", device_stress)

    def test_prepack_is_disabled_by_default_across_public_harmony_layers(self) -> None:
        core = (
            REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Types.ets"
        ).read_text(encoding="utf-8")
        dingqiao = (
            REPO_ROOT
            / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/"
            "SpeechRecognizeSdk.ets"
        ).read_text(encoding="utf-8")
        docs = (
            REPO_ROOT / "delivery/harmony-dingqiao/docs/语音识别SDK接口.md"
        ).read_text(encoding="utf-8")

        self.assertIn("disablePrepack: boolean = true;", core)
        self.assertIn(
            "compatibleBooleanParam(params.extraParams, 'disablePrepack', true)",
            dingqiao,
        )
        self.assertIn("| `disablePrepack` | `boolean/number/string` | `true` |", docs)

    def test_sdk_only_packaging_requires_verified_har_source_identity(self) -> None:
        script = (
            REPO_ROOT
            / "delivery/harmony-dingqiao/delivery/pack_dingqiao_harmony_customer_delivery.sh"
        ).read_text(encoding="utf-8")
        self.assertIn('python3 "$SCRIPT_DIR/harmony_build_identity.py" --verify "$BUILD_IDENTITY"', script)
        self.assertLess(
            script.index('harmony_build_identity.py" --verify "$BUILD_IDENTITY"'),
            script.index('payload = json.loads(Path(sys.argv[1]).read_text'),
        )
        self.assertIn(
            'verify-package --platform harmony --version "$VERSION"',
            script,
        )
        self.assertIn('--source-commit "$BUILD_SOURCE_COMMIT"', script)
        self.assertIn('"commit": build_identity["git_commit"]', script)
        self.assertIn("build_identity = json.loads", script)
        self.assertIn('"verified_source_identity"', script)

    def test_sdk_only_changelog_combines_controlled_notes_and_commit_trace(self) -> None:
        script = (
            REPO_ROOT
            / "delivery/harmony-dingqiao/delivery/pack_dingqiao_harmony_customer_delivery.sh"
        ).read_text(encoding="utf-8")

        self.assertIn("docs/CHANGELOG.md", script)
        self.assertIn(".CHANGELOG_COMMITS.md", script)
        self.assertIn("controlled release notes missing", script)
        self.assertIn("## 源码提交明细", script)

    def test_sdk_only_packaging_removes_customer_excluded_branding(self) -> None:
        script = (
            REPO_ROOT
            / "delivery/harmony-dingqiao/delivery/pack_dingqiao_harmony_customer_delivery.sh"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'text.replace("默认并在鼎桥适配层固定为", "默认并在当前适配层固定为")',
            script,
        )

    def test_complete_delivery_contains_all_requested_artifact_groups(self) -> None:
        script = (
            REPO_ROOT
            / "delivery/harmony-dingqiao/delivery/pack_complete_asr_delivery.sh"
        ).read_text(encoding="utf-8")

        for directory in (
            "release-sdk",
            "diagnostics-sdk",
            "diagnostics-demo",
            "demo-source",
        ):
            self.assertIn(directory, script)
        self.assertIn("amphion_asr_demo-diagnostics-signed.hap", script)
        self.assertIn("git -C \"$REPO_ROOT\" archive", script)
        self.assertIn("hvigor/hvigor-config.json5", script)
        self.assertIn("build-identity.json", script)
        self.assertIn("ACCEPTANCE-SUMMARY.md", script)
        self.assertIn("acceptance-manifest.json", script)
        self.assertIn('identity.get("build_mode") != "diagnostics"', script)
        self.assertIn('required_modes = {"speaker-vad-turn", "customer-ptt"}', script)
        self.assertIn("demo-source/libs/amphion_dingqiao.har", script)
        self.assertIn("!engine.isBusy(), CANCEL_DRAIN_TIMEOUT_MS", script)
        self.assertIn("AmphionRuntime.eagerWarmupSamples()", script)
        self.assertIn('provenance.get("source", {}).get("commit")', script)
        self.assertIn('identity.get("git_commit")', script)
        self.assertIn("def replace_exact", script)
        self.assertIn("expected one demo module", script)
        self.assertIn("TRANSFORMATIONS.md", script)
        self.assertIn("基于本交付 commit 裁剪并适配", script)

    def test_diagnostics_package_can_reuse_the_verified_signed_build(self) -> None:
        script = (
            REPO_ROOT / "delivery/harmony-dingqiao/delivery/pack_diagnostics_sdk.sh"
        ).read_text(encoding="utf-8")
        smoke = (
            REPO_ROOT / "delivery/harmony-dingqiao/delivery/build_install_smoke.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('${SKIP_BUILD:-false}', script)
        self.assertIn('OUTPUT_ROOT="$PWD/$OUTPUT_ROOT"', script)
        self.assertIn('--verify "$VERIFIED_BUILD_IDENTITY"', script)
        self.assertIn("--build-mode diagnostics", script)
        self.assertIn('--build-mode MODE', smoke)
        self.assertIn('buildMode="$BUILD_MODE"', smoke)
        self.assertIn('IDENTITY_ARGS+=(--build-mode "$BUILD_MODE")', smoke)

    def test_speaker_vad_defaults_match_sdk_demo_and_public_docs(self) -> None:
        sdk = (
            REPO_ROOT
            / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/"
            "SpeechRecognizeSdk.ets"
        ).read_text(encoding="utf-8")
        demo = (
            REPO_ROOT
            / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/pages/"
            "Index.ets"
        ).read_text(encoding="utf-8")
        docs = (
            REPO_ROOT / "delivery/harmony-dingqiao/docs/语音识别SDK接口.md"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "clamp(numberParam(extra, 'speakerVadThreshold', 0.35), -1.0, 1.0)",
            sdk,
        )
        self.assertIn(
            "clamp(numberParam(extra, 'speakerVadWindowMs', 1500), 500, 5000)",
            sdk,
        )
        self.assertIn(
            "clamp(numberParam(extra, 'speakerVadHopMs', 500), 100, 2000)",
            sdk,
        )
        self.assertIn("SPEAKER_VAD_THRESHOLD = 0.35", demo)
        self.assertIn("SPEAKER_VAD_WINDOW_MS = 1500", demo)
        self.assertIn("SPEAKER_VAD_HOP_MS = 500", demo)
        self.assertIn("| `speakerVadThreshold` | `number/string` | `0.35` |", docs)
        self.assertIn("| `speakerVadWindowMs` | `number/string` | `1500` |", docs)
        self.assertIn("| `speakerVadHopMs` | `number/string` | `500` |", docs)


if __name__ == "__main__":
    unittest.main()
