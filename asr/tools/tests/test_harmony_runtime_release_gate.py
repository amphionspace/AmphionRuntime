import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/RuntimeReleaseGate.ts"
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
ADAPTER = REPO_ROOT / (
    "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)
LATEST_REQUEST_GATE = REPO_ROOT / (
    "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/LatestRequestGate.ts"
)


class HarmonyRuntimeReleaseGateTest(unittest.TestCase):
    def run_gate(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ RuntimeReleaseGate }} from {GATE.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def run_latest_request_gate(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ LatestRequestGate }} from {LATEST_REQUEST_GATE.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_runtime_release_waits_for_every_session_to_quiesce(self) -> None:
        self.run_gate(
            """
            const events = [];
            const gate = new RuntimeReleaseGate();
            const firstLease = gate.retainSession();
            const secondLease = gate.retainSession();
            assert.notEqual(firstLease, undefined);
            assert.notEqual(secondLease, undefined);

            let firstResolved = false;
            let secondResolved = false;
            const first = gate.requestRuntimeRelease(() => events.push('release'))
              .then(() => { firstResolved = true; });
            const second = gate.requestRuntimeRelease(() => events.push('duplicate-release'))
              .then(() => { secondResolved = true; });

            assert.equal(gate.isReleasePending(), true);
            assert.equal(gate.retainSession(), undefined);
            assert.deepEqual(events, []);
            firstLease.release();
            await Promise.resolve();
            assert.deepEqual(events, []);
            assert.equal(firstResolved, false);
            assert.equal(secondResolved, false);

            secondLease.release();
            await Promise.all([first, second]);
            assert.deepEqual(events, ['release']);
            assert.equal(firstResolved, true);
            assert.equal(secondResolved, true);
            assert.equal(gate.isReleasePending(), false);
            """
        )

    def test_runtime_release_supersedes_deferred_model_unload(self) -> None:
        self.run_gate(
            """
            const events = [];
            const gate = new RuntimeReleaseGate();
            const lease = gate.retainSession();
            assert.notEqual(lease, undefined);
            assert.equal(gate.requestModelUnload(() => events.push('model')), true);
            const released = gate.requestRuntimeRelease(() => events.push('runtime'));
            lease.release();
            await released;
            assert.deepEqual(events, ['runtime']);
            """
        )

    def test_runtime_release_supersedes_model_unload_during_close_retry(self) -> None:
        self.run_gate(
            """
            const events = [];
            const gate = new RuntimeReleaseGate();
            const lease = gate.retainSession();
            assert.notEqual(lease, undefined);
            let closeAttempts = 0;
            const close = () => {
              closeAttempts += 1;
              if (closeAttempts < 3) throw new Error('temporary close failure');
              events.push('stream-closed');
            };

            assert.equal(lease.releaseAfterClose(close), false);
            assert.equal(gate.requestModelUnload(() => events.push('model')), true);
            const released = gate.requestRuntimeRelease(() => events.push('runtime'));
            await released;
            assert.deepEqual(events, ['stream-closed', 'runtime']);
            assert.equal(gate.isReleasePending(), false);
            """
        )

    def test_model_unload_is_immediate_when_no_session_is_active(self) -> None:
        self.run_gate(
            """
            const events = [];
            const gate = new RuntimeReleaseGate();
            assert.equal(gate.requestModelUnload(() => events.push('model')), false);
            assert.deepEqual(events, ['model']);
            assert.equal(gate.isReleasePending(), false);
            """
        )

    def test_failed_close_does_not_drop_pending_model_unload(self) -> None:
        self.run_gate(
            """
            const events = [];
            const gate = new RuntimeReleaseGate();
            const lease = gate.retainSession();
            assert.notEqual(lease, undefined);
            let closeAttempts = 0;
            const close = () => {
              closeAttempts += 1;
              if (closeAttempts < 3) throw new Error('temporary close failure');
              events.push('stream-closed');
            };

            assert.equal(lease.releaseAfterClose(close), false);
            assert.equal(gate.requestModelUnload(() => events.push('first-unload')), true);
            assert.equal(gate.isReleasePending(), true);
            assert.deepEqual(events, []);

            assert.equal(gate.requestModelUnload(() => events.push('duplicate-unload')), false);
            assert.deepEqual(events, ['stream-closed', 'first-unload']);
            assert.equal(gate.isReleasePending(), false);
            """
        )

    def test_failed_stream_close_keeps_runtime_release_blocked_until_retry_succeeds(self) -> None:
        self.run_gate(
            """
            const events = [];
            const gate = new RuntimeReleaseGate();
            const lease = gate.retainSession();
            assert.notEqual(lease, undefined);
            let resolved = false;
            let closeAttempts = 0;
            const close = () => {
              closeAttempts += 1;
              if (closeAttempts === 1) throw new Error('close failed');
              events.push('stream-closed');
            };
            const released = gate.requestRuntimeRelease(() => events.push('stale-runtime'))
              .then(() => { resolved = true; }, () => { events.push('release-rejected'); });

            assert.equal(lease.releaseAfterClose(close), false);
            await released;
            assert.deepEqual(events, ['release-rejected']);
            assert.equal(resolved, false);
            assert.equal(gate.isReleasePending(), false);
            const nextLease = gate.retainSession();
            assert.notEqual(nextLease, undefined);
            nextLease.release();

            const retried = gate.requestRuntimeRelease(() => events.push('runtime'))
              .then(() => { resolved = true; });
            await retried;
            assert.deepEqual(events, ['release-rejected', 'stream-closed', 'runtime']);
            assert.equal(resolved, true);
            assert.equal(gate.isReleasePending(), false);
            """
        )

    def test_session_retry_cannot_release_the_same_lease_twice(self) -> None:
        self.run_gate(
            """
            const events = [];
            const gate = new RuntimeReleaseGate();
            const failedLease = gate.retainSession();
            const activeLease = gate.retainSession();
            assert.notEqual(failedLease, undefined);
            assert.notEqual(activeLease, undefined);
            let attempts = 0;
            const close = () => {
              attempts += 1;
              if (attempts === 1) throw new Error('first close fails');
            };
            assert.equal(failedLease.releaseAfterClose(close), false);
            assert.equal(failedLease.retryClose(), true);
            assert.equal(failedLease.retryClose(), true);

            let resolved = false;
            const released = gate.requestRuntimeRelease(() => events.push('runtime'))
              .then(() => { resolved = true; });
            await Promise.resolve();
            assert.equal(resolved, false);
            assert.deepEqual(events, []);
            activeLease.release();
            await released;
            assert.deepEqual(events, ['runtime']);
            """
        )

    def test_retried_stream_close_notifies_owner_once(self) -> None:
        self.run_gate(
            """
            const events = [];
            const gate = new RuntimeReleaseGate();
            const lease = gate.retainSession();
            assert.notEqual(lease, undefined);
            let closeAttempts = 0;
            let ownerNotifications = 0;
            const closeAndNotifyOwner = () => {
              closeAttempts += 1;
              if (closeAttempts === 1) throw new Error('first close fails');
              events.push('stream-closed');
              ownerNotifications += 1;
            };

            assert.equal(lease.releaseAfterClose(closeAndNotifyOwner), false);
            assert.equal(ownerNotifications, 0);
            assert.equal(gate.requestModelUnload(() => events.push('model')), false);
            assert.deepEqual(events, ['stream-closed', 'model']);
            assert.equal(ownerNotifications, 1);
            assert.equal(lease.retryClose(), true);
            assert.equal(ownerNotifications, 1);
            """
        )

    def test_throwing_runtime_release_rejects_every_waiter(self) -> None:
        self.run_gate(
            """
            const gate = new RuntimeReleaseGate();
            const first = gate.requestRuntimeRelease(() => { throw new Error('release failed'); });
            await assert.rejects(first, /Runtime release failed/);
            assert.equal(gate.isReleasePending(), false);

            const lease = gate.retainSession();
            assert.notEqual(lease, undefined);
            const second = gate.requestRuntimeRelease(() => { throw new Error('deferred failed'); });
            const third = gate.requestRuntimeRelease(() => {});
            lease.release();
            await assert.rejects(second, /Runtime release failed/);
            await assert.rejects(third, /Runtime release failed/);
            assert.equal(gate.isReleasePending(), false);
            """
        )

    def test_only_latest_license_request_publishes_across_deferred_release(self) -> None:
        self.run_latest_request_gate(
            """
            const gate = new LatestRequestGate();
            const published = [];
            let resumeOld;
            const oldDrain = new Promise(resolve => { resumeOld = resolve; });
            const oldRequest = gate.begin();
            const oldFlow = (async () => {
              await oldDrain;
              if (gate.isCurrent(oldRequest)) published.push('old');
            })();

            const newRequest = gate.begin();
            resumeOld();
            await oldFlow;
            if (gate.isCurrent(newRequest)) published.push('new');
            assert.deepEqual(published, ['new']);

            const delayedRequest = gate.begin();
            gate.begin(); // A newer invalid request still supersedes the delayed valid request.
            if (gate.isCurrent(delayedRequest)) published.push('stale-valid');
            assert.deepEqual(published, ['new']);
            """
        )

    def test_runtime_and_adapter_use_the_release_gate(self) -> None:
        runtime = RUNTIME.read_text(encoding="utf-8")
        adapter = ADAPTER.read_text(encoding="utf-8")
        self.assertIn("from './RuntimeReleaseGate'", runtime)
        self.assertIn("releaseAsync(): Promise<void>", runtime)
        release_guard = runtime.split("private releaseStreamIfClosed(): void", 1)[1]
        self.assertIn("this.streamCallDepth > 0", release_guard)
        self.assertIn("this.runtimeLease.releaseAfterClose", release_guard)
        release_close_action = release_guard.split(
            "this.runtimeLease.releaseAfterClose((): void => {", 1
        )[1].split("}))", 1)[0]
        self.assertIn("this.stream.close()", release_close_action)
        self.assertIn("this.streamReleased = true", release_close_action)
        self.assertIn("this.onStreamReleased()", release_close_action)
        new_session = runtime.split("newSession(callback: AsrCallback", 1)[1].split(
            "isClosed(): boolean", 1
        )[0]
        self.assertIn("stream = this.recognizer.createStream()", new_session)
        self.assertIn("lease.releaseAfterClose", new_session)
        construction_close_action = new_session.split(
            "lease.releaseAfterClose((): void => {", 1
        )[1].split("}))", 1)[0]
        self.assertIn("createdStream.close()", construction_close_action)
        self.assertIn("this.onSessionStreamReleased()", construction_close_action)
        constructor = runtime.split("export class AsrSession", 1)[1].split(
            "acceptPcmShort", 1
        )[0]
        self.assertIn("stream: OnlineStream", constructor)
        self.assertIn("runtimeLease: RuntimeSessionLease", constructor)
        self.assertNotIn("recognizer.createStream()", constructor)
        self.assertIn("AmphionRuntime.releaseVad", constructor)
        self.assertGreaterEqual(runtime.count("if (e instanceof Error) throw e"), 2)
        self.assertIn("await SpeechRecognizeSdk.invalidateRuntimeAsync()", adapter)
        adapter_release = adapter.split(
            "private static async invalidateRuntimeAsync(): Promise<void>", 1
        )[1].split("static createEngine", 1)[0]
        self.assertIn(
            "await SpeakerDiarizationRuntimeLeaseRegistry.beginRelease()",
            adapter_release,
        )
        self.assertIn("await AmphionRuntime.releaseAsync()", adapter_release)
        self.assertIn(
            "SpeakerDiarizationRuntimeLeaseRegistry.endRelease()",
            adapter_release,
        )
        self.assertLess(
            adapter_release.index("SpeakerDiarizationRuntimeLeaseRegistry.beginRelease()"),
            adapter_release.index("AmphionRuntime.releaseAsync()"),
        )
        self.assertIn("finally", adapter_release)
        self.assertIn("AmphionRuntime.isReleasePending()", adapter)
        self.assertGreaterEqual(adapter.count("licenseRequests.isCurrent(requestGeneration)"), 3)


if __name__ == "__main__":
    unittest.main()
