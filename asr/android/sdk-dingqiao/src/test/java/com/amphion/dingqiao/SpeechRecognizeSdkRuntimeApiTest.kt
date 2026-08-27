package com.amphion.dingqiao

import android.content.Context
import com.amphion.asr.AmphionLicenseStatus
import com.amphion.asr.AmphionLogLevel
import com.amphion.asr.AmphionOptions
import com.amphion.asr.AsrCallback
import com.amphion.asr.AsrEngine
import com.amphion.asr.AsrErrorCode
import com.amphion.asr.AsrResult
import com.amphion.asr.AsrSession
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.mockito.kotlin.any
import org.mockito.kotlin.doReturn
import org.mockito.kotlin.mock
import org.mockito.kotlin.verify
import org.mockito.kotlin.whenever

class SpeechRecognizeSdkRuntimeApiTest {
    @Before
    fun resetBeforeTest() {
        SpeechRecognizeSdk.resetForTests()
    }

    @After
    fun resetAfterTest() {
        SpeechRecognizeSdk.resetForTests()
    }

    @Test
    fun workPathRoundTripsLikeHarmonyApi() {
        assertEquals("", SpeechRecognizeSdk.getWorkPath())
        val directory = kotlin.io.path.createTempDirectory("dingqiao-work-path").toFile()
        try {
            SpeechRecognizeSdk.setWorkPath(directory.path)
            assertEquals(directory.path, SpeechRecognizeSdk.getWorkPath())
        } finally {
            directory.delete()
        }
    }

    @Test
    fun recognitionModeAliasesMatchHarmonyApi() {
        assertEquals(DingqiaoRecognitionMode.RECORD, DingqiaoRecognitionMode.SINGLE)
        assertEquals(DingqiaoRecognitionMode.STREAM, DingqiaoRecognitionMode.CONTINUOUS)
    }

    @Test
    fun prepareRuntimeBeforeInitReportsEngineNotInitialized() {
        var ready = false
        var errorCode: Int? = null

        SpeechRecognizeSdk.prepareRuntime(
            object : PrepareRuntimeCallback {
                override fun onReady() {
                    ready = true
                }

                override fun onError(errorCodeValue: Int, errorMessage: String) {
                    errorCode = errorCodeValue
                }
            },
        )

        assertFalse(ready)
        assertEquals(DingqiaoErrorCode.ENGINE_NOT_INITIALIZED, errorCode)
    }

    @Test
    fun setLicenseDoesNotPrepareRuntime() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val licenseFile = kotlin.io.path.createTempFile(suffix = ".lic").toFile()
        licenseFile.writeText("development-license")
        val licenseDone = CountDownLatch(1)
        val runtimeDone = CountDownLatch(1)
        var runtimeError: Int? = null
        var licenseError: Int? = null
        var licenseErrorMessage: String? = null
        val runtime = FakeRuntimeLifecycleBridge()
        SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)

        SpeechRecognizeSdk.init(context)
        SpeechRecognizeSdk.setLicense(
            licenseFile.absolutePath,
            object : LicenseActivationCallback {
                override fun onResult(result: LicenseActivationResult) {
                    licenseDone.countDown()
                }

                override fun onError(errorCode: Int, errorMessage: String) {
                    licenseError = errorCode
                    licenseErrorMessage = errorMessage
                    licenseDone.countDown()
                }
            },
        )

        assertTrue(licenseDone.await(5, TimeUnit.SECONDS))
        assertEquals(licenseErrorMessage, null, licenseError)
        assertFalse(runtime.ready)
        assertEquals(0, SpeechRecognizeSdk.getLicenseInfo().status)

        SpeechRecognizeSdk.prepareRuntime(
            object : PrepareRuntimeCallback {
                override fun onReady() {
                    runtimeDone.countDown()
                }

                override fun onError(errorCode: Int, errorMessage: String) {
                    runtimeError = errorCode
                    runtimeDone.countDown()
                }
            },
        )

        assertTrue(runtimeDone.await(5, TimeUnit.SECONDS))
        assertEquals(null, runtimeError)
        assertTrue(runtime.ready)
        licenseFile.delete()
    }

    @Test
    fun configuredLogLevelFlowsThroughLicenseValidationAndRuntimePreparation() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val licenseFile = kotlin.io.path.createTempFile(suffix = ".lic").toFile()
        licenseFile.writeText("development-license")
        val licenseDone = CountDownLatch(1)
        val prepareDone = CountDownLatch(1)
        val runtime = FakeRuntimeLifecycleBridge()
        SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)
        SpeechRecognizeSdk.init(context)
        SpeechRecognizeSdk.setLogLevel(AmphionLogLevel.DEBUG)

        SpeechRecognizeSdk.setLicense(
            licenseFile.absolutePath,
            object : LicenseActivationCallback {
                override fun onResult(result: LicenseActivationResult) = licenseDone.countDown()
                override fun onError(errorCode: Int, errorMessage: String) = licenseDone.countDown()
            },
        )
        assertTrue(licenseDone.await(5, TimeUnit.SECONDS))

        SpeechRecognizeSdk.prepareRuntime(
            object : PrepareRuntimeCallback {
                override fun onReady() = prepareDone.countDown()
                override fun onError(errorCode: Int, errorMessage: String) = prepareDone.countDown()
            },
        )

        assertTrue(prepareDone.await(5, TimeUnit.SECONDS))
        assertEquals(AmphionLogLevel.DEBUG, runtime.lastValidatedLogLevel)
        assertEquals(AmphionLogLevel.DEBUG, runtime.lastPreparedLogLevel)
        licenseFile.delete()
    }

    @Test
    fun normalBuildRejectsDiagnosticsExportWithoutChangingRuntimeState() {
        if (BuildConfig.DIAGNOSTICS_ENABLED) return
        val callbackDone = CountDownLatch(1)
        val errors = CopyOnWriteArrayList<Pair<Int, String>>()

        SpeechRecognizeSdk.exportDiagnostics(object : DiagnosticExportCallback {
            override fun onSuccess(path: String) {
                callbackDone.countDown()
            }

            override fun onError(errorCode: Int, errorMessage: String) {
                errors += errorCode to errorMessage
                callbackDone.countDown()
            }
        })

        assertTrue(callbackDone.await(5, TimeUnit.SECONDS))
        assertEquals(1, errors.size)
        assertEquals(DingqiaoErrorCode.INTERNAL_ERROR, errors.single().first)
        assertTrue(errors.single().second.contains("not enabled"))
    }

    @Test
    fun finishThenRelicenseWaitsForLastCompleteBeforeRuntimeRelease() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val runtime = FakeRuntimeLifecycleBridge().apply { ready = true }
        val nativeCallbacks = ConcurrentLinkedQueue<AsrCallback>()
        val nativeSession = mock<AsrSession>()
        val asrEngine = mock<AsrEngine>()
        whenever(asrEngine.newSession(any(), any())).thenAnswer { invocation ->
            nativeCallbacks.add(invocation.getArgument(0))
            nativeSession
        }
        val callbackExecutor = Executors.newSingleThreadExecutor()
        val workPath = kotlin.io.path.createTempDirectory().toFile()
        val callbackEvents = CopyOnWriteArrayList<String>()
        val sessionComplete = CountDownLatch(1)
        val licenseDone = CountDownLatch(1)
        val licenseFile = kotlin.io.path.createTempFile(suffix = ".lic").toFile()
        licenseFile.writeText("replacement-license")
        val publicEngine = DingqiaoRecognitionEngine(
            appContext = context,
            createParams = CreateEngineParams(language = "zh-CN"),
            voiceprintStore = VoiceprintStore(workPath),
            speakerModelPath = null,
            callbackExecutor = callbackExecutor,
            onShutdown = {},
            preloadedEngine = asrEngine,
            injectedTextEnhancer = { it },
        )
        publicEngine.setListener(object : RecognitionListener {
            override fun onStart(sessionId: String, eventMessage: String) = Unit
            override fun onEvent(sessionId: String, eventCode: Int, eventMessage: String) = Unit
            override fun onResult(sessionId: String, result: SpeechRecognitionResult) {
                if (result.isLast) callbackEvents += "last:${result.result}"
            }
            override fun onComplete(sessionId: String, eventMessage: String) {
                callbackEvents += "complete"
                sessionComplete.countDown()
            }
            override fun onError(sessionId: String, errorCode: Int, errorMessage: String) = Unit
        })

        try {
            SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)
            SpeechRecognizeSdk.init(context)
            SpeechRecognizeSdk.trackEngine(publicEngine)
            publicEngine.startListening(StartParams("finish-relicense", AudioInfo()))
            val nativeCallback = nativeCallbacks.remove()
            publicEngine.finish("finish-relicense")

            SpeechRecognizeSdk.setLicense(
                licenseFile.absolutePath,
                object : LicenseActivationCallback {
                    override fun onResult(result: LicenseActivationResult) = licenseDone.countDown()
                    override fun onError(errorCode: Int, errorMessage: String) = licenseDone.countDown()
                },
            )

            assertFalse(
                "relicense must wait while terminal native work is still active",
                licenseDone.await(100, TimeUnit.MILLISECONDS),
            )
            assertEquals(0, runtime.unloadCalls.get())

            nativeCallback.onFinal(AsrResult(text = "重授权前完成", isLast = true))

            assertTrue(sessionComplete.await(5, TimeUnit.SECONDS))
            assertTrue(licenseDone.await(5, TimeUnit.SECONDS))
            assertEquals(listOf("last:重授权前完成", "complete"), callbackEvents.toList())
            assertEquals(1, runtime.unloadCalls.get())
            verify(asrEngine).close()
        } finally {
            publicEngine.shutdown()
            callbackExecutor.shutdownNow()
            licenseFile.delete()
            workPath.deleteRecursively()
        }
    }

    @Test
    fun createEngineAsyncBeforePrepareReportsEngineNotInitialized() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val done = CountDownLatch(1)
        var errorCode: Int? = null
        SpeechRecognizeSdk.init(context)

        SpeechRecognizeSdk.createEngineAsync(
            CreateEngineParams(language = "zh"),
            object : CreateEngineCallback {
                override fun onSuccess(engine: SpeechRecognitionEngine) {
                    done.countDown()
                }

                override fun onError(errorCodeValue: Int, errorMessage: String) {
                    errorCode = errorCodeValue
                    done.countDown()
                }
            },
        )

        assertTrue(done.await(5, TimeUnit.SECONDS))
        assertEquals(DingqiaoErrorCode.ENGINE_NOT_INITIALIZED, errorCode)
    }

    @Test
    fun successfulSetLicenseShutsDownPublishedEngineBeforeRuntimeReset() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val licenseFile = kotlin.io.path.createTempFile(suffix = ".lic").toFile()
        licenseFile.writeText("development-license")
        val runtime = FakeRuntimeLifecycleBridge().apply { ready = true }
        val engine = mock<SpeechRecognitionEngine>()
        val done = CountDownLatch(1)
        SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)
        SpeechRecognizeSdk.init(context)
        SpeechRecognizeSdk.trackEngine(engine)

        SpeechRecognizeSdk.setLicense(
            licenseFile.absolutePath,
            object : LicenseActivationCallback {
                override fun onResult(result: LicenseActivationResult) = done.countDown()
                override fun onError(errorCode: Int, errorMessage: String) = done.countDown()
            },
        )

        assertTrue(done.await(5, TimeUnit.SECONDS))
        verify(engine).shutdown()
        assertFalse(runtime.ready)
        licenseFile.delete()
    }

    @Test
    fun newSuccessCallbackBridgesToLegacyOnResultImplementation() {
        var received: SpeechRecognitionEngine? = null
        val engine = mock<SpeechRecognitionEngine>()
        val legacy = object : CreateEngineCallback {
            @Suppress("DEPRECATION")
            override fun onResult(engine: SpeechRecognitionEngine) {
                received = engine
            }
        }

        legacy.onSuccess(engine)

        assertEquals(engine, received)
    }

    @Test
    fun concurrentPrepareRuntimeIsSingleFlightAndUnloadPreservesLicense() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val licenseFile = kotlin.io.path.createTempFile(suffix = ".lic").toFile()
        licenseFile.writeText("development-license")
        val runtime = FakeRuntimeLifecycleBridge()
        SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)
        SpeechRecognizeSdk.init(context)
        val licensed = CountDownLatch(1)
        SpeechRecognizeSdk.setLicense(
            licenseFile.absolutePath,
            object : LicenseActivationCallback {
                override fun onResult(result: LicenseActivationResult) = licensed.countDown()
                override fun onError(errorCode: Int, errorMessage: String) = licensed.countDown()
            },
        )
        assertTrue(licensed.await(5, TimeUnit.SECONDS))

        val prepared = CountDownLatch(2)
        repeat(2) {
            SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
                override fun onReady() = prepared.countDown()
                override fun onError(errorCode: Int, errorMessage: String) = prepared.countDown()
            })
        }

        assertTrue(prepared.await(5, TimeUnit.SECONDS))
        assertEquals(1, runtime.prepareCalls.get())

        SpeechRecognizeSdk.unloadModel()
        val modelRePrepared = CountDownLatch(1)
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() = modelRePrepared.countDown()
        })
        assertTrue(modelRePrepared.await(5, TimeUnit.SECONDS))
        assertEquals(2, runtime.prepareCalls.get())

        SpeechRecognizeSdk.unloadRuntime()
        assertEquals(0, SpeechRecognizeSdk.getLicenseInfo().status)

        val rePrepared = CountDownLatch(1)
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() = rePrepared.countDown()
        })
        assertTrue(rePrepared.await(5, TimeUnit.SECONDS))
        assertEquals(3, runtime.prepareCalls.get())
        licenseFile.delete()
    }

    @Test
    fun unloadRuntimeSerializesWithBlockedPrepareAndLeavesRuntimeUnloaded() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val licenseFile = kotlin.io.path.createTempFile(suffix = ".lic").toFile()
        licenseFile.writeText("development-license")
        val runtime = FakeRuntimeLifecycleBridge().apply {
            blockPrepare = true
        }
        SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)
        SpeechRecognizeSdk.init(context)
        val licensed = CountDownLatch(1)
        SpeechRecognizeSdk.setLicense(
            licenseFile.absolutePath,
            object : LicenseActivationCallback {
                override fun onResult(result: LicenseActivationResult) = licensed.countDown()
                override fun onError(errorCode: Int, errorMessage: String) = licensed.countDown()
            },
        )
        assertTrue(licensed.await(5, TimeUnit.SECONDS))

        val prepareCallback = CountDownLatch(1)
        var prepareReady = false
        var prepareError: Int? = null
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() {
                prepareReady = true
                prepareCallback.countDown()
            }

            override fun onError(errorCode: Int, errorMessage: String) {
                prepareError = errorCode
                prepareCallback.countDown()
            }
        })
        assertTrue(runtime.prepareStarted.await(5, TimeUnit.SECONDS))

        val unload = Thread { SpeechRecognizeSdk.unloadRuntime() }
        unload.start()
        unload.join(200)
        assertTrue("unloadRuntime must serialize behind an active prepare", unload.isAlive)

        runtime.releasePrepare.countDown()
        assertTrue(prepareCallback.await(5, TimeUnit.SECONDS))
        unload.join(5_000)
        assertFalse("unloadRuntime must finish after prepare exits", unload.isAlive)
        assertTrue(prepareReady)
        assertEquals(null, prepareError)
        assertFalse("unloadRuntime return must leave native runtime unloaded", runtime.ready)
        licenseFile.delete()
    }

    @Test
    fun failedPrepareRollsBackRuntimeAndCanRetry() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val licenseFile = kotlin.io.path.createTempFile(suffix = ".lic").toFile()
        licenseFile.writeText("development-license")
        val runtime = FakeRuntimeLifecycleBridge().apply {
            failPrepareAfterReady = true
        }
        SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)
        SpeechRecognizeSdk.init(context)
        val licensed = CountDownLatch(1)
        SpeechRecognizeSdk.setLicense(
            licenseFile.absolutePath,
            object : LicenseActivationCallback {
                override fun onResult(result: LicenseActivationResult) = licensed.countDown()
                override fun onError(errorCode: Int, errorMessage: String) = licensed.countDown()
            },
        )
        assertTrue(licensed.await(5, TimeUnit.SECONDS))

        val failed = CountDownLatch(1)
        var errorCode: Int? = null
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() = failed.countDown()
            override fun onError(errorCodeValue: Int, errorMessage: String) {
                errorCode = errorCodeValue
                failed.countDown()
            }
        })
        assertTrue(failed.await(5, TimeUnit.SECONDS))
        assertEquals(DingqiaoErrorCode.ENGINE_NOT_INITIALIZED, errorCode)
        assertFalse("failed prepare must roll back native runtime", runtime.ready)
        assertEquals(1, runtime.unloadCalls.get())

        runtime.failPrepareAfterReady = false
        val retried = CountDownLatch(1)
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() = retried.countDown()
        })
        assertTrue(retried.await(5, TimeUnit.SECONDS))
        assertTrue(runtime.ready)
        licenseFile.delete()
    }

    @Test
    fun concurrentFailedPrepareSharesOneFailureAndCanRetryLater() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val licenseFile = kotlin.io.path.createTempFile(suffix = ".lic").toFile()
        licenseFile.writeText("development-license")
        val runtime = FakeRuntimeLifecycleBridge().apply {
            blockPrepare = true
            failPrepareAfterReady = true
        }
        SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)
        SpeechRecognizeSdk.init(context)
        val licensed = CountDownLatch(1)
        SpeechRecognizeSdk.setLicense(
            licenseFile.absolutePath,
            object : LicenseActivationCallback {
                override fun onResult(result: LicenseActivationResult) = licensed.countDown()
                override fun onError(errorCode: Int, errorMessage: String) = licensed.countDown()
            },
        )
        assertTrue(licensed.await(5, TimeUnit.SECONDS))

        val failed = CountDownLatch(2)
        val readyCount = AtomicInteger()
        val errorCodes = mutableListOf<Int>()
        val callback = object : PrepareRuntimeCallback {
            override fun onReady() {
                readyCount.incrementAndGet()
                failed.countDown()
            }

            override fun onError(errorCode: Int, errorMessage: String) {
                synchronized(errorCodes) {
                    errorCodes += errorCode
                }
                failed.countDown()
            }
        }
        SpeechRecognizeSdk.prepareRuntime(callback)
        assertTrue(runtime.prepareStarted.await(5, TimeUnit.SECONDS))
        SpeechRecognizeSdk.prepareRuntime(callback)
        runtime.releasePrepare.countDown()

        assertTrue(failed.await(5, TimeUnit.SECONDS))
        assertEquals(0, readyCount.get())
        assertEquals(
            listOf(
                DingqiaoErrorCode.ENGINE_NOT_INITIALIZED,
                DingqiaoErrorCode.ENGINE_NOT_INITIALIZED,
            ),
            synchronized(errorCodes) { errorCodes.toList() },
        )
        assertEquals(1, runtime.prepareCalls.get())
        assertEquals(1, runtime.unloadCalls.get())
        assertFalse("failed prepare must leave native runtime unloaded", runtime.ready)

        runtime.blockPrepare = false
        runtime.failPrepareAfterReady = false
        val retried = CountDownLatch(1)
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() = retried.countDown()
        })
        assertTrue(retried.await(5, TimeUnit.SECONDS))
        assertEquals(2, runtime.prepareCalls.get())
        assertTrue(runtime.ready)
        licenseFile.delete()
    }

    @Test
    fun reentrantUnloadInvalidatesRemainingPrepareWaiters() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val licenseFile = kotlin.io.path.createTempFile(suffix = ".lic").toFile()
        licenseFile.writeText("development-license")
        val runtime = FakeRuntimeLifecycleBridge().apply {
            blockPrepare = true
        }
        SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)
        SpeechRecognizeSdk.init(context)
        val licensed = CountDownLatch(1)
        SpeechRecognizeSdk.setLicense(
            licenseFile.absolutePath,
            object : LicenseActivationCallback {
                override fun onResult(result: LicenseActivationResult) = licensed.countDown()
                override fun onError(errorCode: Int, errorMessage: String) = licensed.countDown()
            },
        )
        assertTrue(licensed.await(5, TimeUnit.SECONDS))

        val callbacks = CountDownLatch(2)
        var firstReady = false
        var secondReady = false
        var secondError: Int? = null
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() {
                firstReady = true
                SpeechRecognizeSdk.unloadRuntime()
                callbacks.countDown()
            }
        })
        assertTrue(runtime.prepareStarted.await(5, TimeUnit.SECONDS))
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() {
                secondReady = true
                callbacks.countDown()
            }

            override fun onError(errorCode: Int, errorMessage: String) {
                secondError = errorCode
                callbacks.countDown()
            }
        })
        runtime.releasePrepare.countDown()

        assertTrue(callbacks.await(5, TimeUnit.SECONDS))
        assertTrue(firstReady)
        assertFalse(secondReady)
        assertEquals(DingqiaoErrorCode.ENGINE_NOT_INITIALIZED, secondError)
        assertFalse(runtime.ready)
        assertEquals(1, runtime.prepareCalls.get())
        licenseFile.delete()
    }

    @Test
    fun unloadModelInvalidatesQueuedFlightWithoutLateStateRollback() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val licenseFile = kotlin.io.path.createTempFile(suffix = ".lic").toFile()
        licenseFile.writeText("development-license")
        val runtime = FakeRuntimeLifecycleBridge()
        SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)
        SpeechRecognizeSdk.init(context)
        val licensed = CountDownLatch(1)
        SpeechRecognizeSdk.setLicense(
            licenseFile.absolutePath,
            object : LicenseActivationCallback {
                override fun onResult(result: LicenseActivationResult) = licensed.countDown()
                override fun onError(errorCode: Int, errorMessage: String) = licensed.countDown()
            },
        )
        assertTrue(licensed.await(5, TimeUnit.SECONDS))

        val executor = ManuallyOrderedExecutor()
        SpeechRecognizeSdk.setEngineExecutorForTests(executor)
        var oldError: Int? = null
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() = Unit

            override fun onError(errorCode: Int, errorMessage: String) {
                oldError = errorCode
            }
        })
        assertEquals(1, executor.size)

        SpeechRecognizeSdk.unloadModel()
        var newReady = false
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() {
                newReady = true
            }
        })
        assertEquals(2, executor.size)

        executor.runAt(1)
        assertTrue(newReady)
        assertEquals(1, runtime.prepareCalls.get())
        executor.runAt(0)
        assertEquals(DingqiaoErrorCode.ENGINE_NOT_INITIALIZED, oldError)

        var stillReady = false
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() {
                stillReady = true
            }
        })
        assertTrue("stale flight failure must not clear the newer ready state", stillReady)
        assertEquals(0, executor.size)
        assertEquals(1, runtime.prepareCalls.get())
        licenseFile.delete()
    }

    @Test
    fun reentrantUnloadModelInvalidatesRemainingPrepareWaiters() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val licenseFile = kotlin.io.path.createTempFile(suffix = ".lic").toFile()
        licenseFile.writeText("development-license")
        val runtime = FakeRuntimeLifecycleBridge().apply {
            blockPrepare = true
        }
        SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)
        SpeechRecognizeSdk.init(context)
        val licensed = CountDownLatch(1)
        SpeechRecognizeSdk.setLicense(
            licenseFile.absolutePath,
            object : LicenseActivationCallback {
                override fun onResult(result: LicenseActivationResult) = licensed.countDown()
                override fun onError(errorCode: Int, errorMessage: String) = licensed.countDown()
            },
        )
        assertTrue(licensed.await(5, TimeUnit.SECONDS))

        val callbacks = CountDownLatch(2)
        var secondError: Int? = null
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() {
                SpeechRecognizeSdk.unloadModel()
                callbacks.countDown()
            }
        })
        assertTrue(runtime.prepareStarted.await(5, TimeUnit.SECONDS))
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() = Unit

            override fun onError(errorCode: Int, errorMessage: String) {
                secondError = errorCode
                callbacks.countDown()
            }
        })
        runtime.releasePrepare.countDown()

        assertTrue(callbacks.await(5, TimeUnit.SECONDS))
        assertEquals(DingqiaoErrorCode.ENGINE_NOT_INITIALIZED, secondError)
        assertEquals(1, runtime.prepareCalls.get())
        licenseFile.delete()
    }

    @Test
    fun latestSetLicenseWinsWhenOlderValidationFinishesLast() {
        val context = mock<Context> {
            on { applicationContext } doReturn null
            on { packageName } doReturn "com.amphion.test"
        }
        val oldLicense = kotlin.io.path.createTempFile(suffix = ".lic").toFile().apply {
            writeText("old-license")
        }
        val newLicense = kotlin.io.path.createTempFile(suffix = ".lic").toFile().apply {
            writeText("new-license")
        }
        val runtime = FakeRuntimeLifecycleBridge().apply {
            blockedLicenseText = "old-license"
        }
        SpeechRecognizeSdk.setRuntimeBridgeForTests(runtime)
        SpeechRecognizeSdk.init(context)
        val callbacks = CountDownLatch(2)

        SpeechRecognizeSdk.setLicense(oldLicense.absolutePath, countingLicenseCallback(callbacks))
        assertTrue(runtime.validationStarted.await(5, TimeUnit.SECONDS))
        SpeechRecognizeSdk.setLicense(newLicense.absolutePath, countingLicenseCallback(callbacks))
        runtime.releaseValidation.countDown()

        assertTrue(callbacks.await(5, TimeUnit.SECONDS))
        val prepared = CountDownLatch(1)
        SpeechRecognizeSdk.prepareRuntime(object : PrepareRuntimeCallback {
            override fun onReady() = prepared.countDown()
        })
        assertTrue(prepared.await(5, TimeUnit.SECONDS))
        assertEquals("new-license", runtime.lastPreparedLicense)
        oldLicense.delete()
        newLicense.delete()
    }

    private fun countingLicenseCallback(done: CountDownLatch) =
        object : LicenseActivationCallback {
            override fun onResult(result: LicenseActivationResult) = done.countDown()
            override fun onError(errorCode: Int, errorMessage: String) = done.countDown()
        }

    private class ManuallyOrderedExecutor : Executor {
        private val tasks = mutableListOf<Runnable>()

        val size: Int
            get() = synchronized(tasks) { tasks.size }

        override fun execute(command: Runnable) {
            synchronized(tasks) {
                tasks += command
            }
        }

        fun runAt(index: Int) {
            val task = synchronized(tasks) {
                tasks.removeAt(index)
            }
            task.run()
        }
    }

    private class FakeRuntimeLifecycleBridge : RuntimeLifecycleBridge {
        @Volatile var ready: Boolean = false
        val prepareCalls = AtomicInteger()
        var blockedLicenseText: String? = null
        @Volatile var blockPrepare: Boolean = false
        @Volatile var failPrepareAfterReady: Boolean = false
        val validationStarted = CountDownLatch(1)
        val releaseValidation = CountDownLatch(1)
        val prepareStarted = CountDownLatch(1)
        val releasePrepare = CountDownLatch(1)
        val unloadCalls = AtomicInteger()
        @Volatile var lastPreparedLicense: String? = null
        @Volatile var lastValidatedLogLevel: AmphionLogLevel? = null
        @Volatile var lastPreparedLogLevel: AmphionLogLevel? = null

        override fun validateLicense(
            context: Context,
            options: AmphionOptions,
        ): AmphionLicenseStatus {
            lastValidatedLogLevel = options.logLevel
            if (options.license == blockedLicenseText) {
                validationStarted.countDown()
                releaseValidation.await(5, TimeUnit.SECONDS)
            }
            return AmphionLicenseStatus(
                state = AmphionLicenseStatus.State.LICENSED,
                valid = true,
                errorCode = AsrErrorCode.OK,
                licenseId = "test",
                customer = "test",
                applicationId = "com.amphion.test",
                bundleName = "",
                signingCertDigest = "",
                deviceIdHashAlg = "",
                deviceIdSaltId = "",
                authorizedDeviceCount = 0,
                maintenanceUntil = "",
                issuedAt = "2026-07-23",
                expiresAt = "2026-11-23",
                installTier = "test",
                features = listOf("ASR"),
            )
        }

        override fun prepareRuntime(context: Context, options: AmphionOptions) {
            prepareCalls.incrementAndGet()
            lastPreparedLicense = options.license
            lastPreparedLogLevel = options.logLevel
            if (blockPrepare) {
                prepareStarted.countDown()
                releasePrepare.await(5, TimeUnit.SECONDS)
            }
            ready = true
            if (failPrepareAfterReady) {
                throw IllegalStateException("prepare failed after runtime init")
            }
        }

        override fun isRuntimeReady(): Boolean = ready

        override fun unloadModel() = Unit

        override fun unloadRuntime() {
            unloadCalls.incrementAndGet()
            ready = false
        }
    }
}
