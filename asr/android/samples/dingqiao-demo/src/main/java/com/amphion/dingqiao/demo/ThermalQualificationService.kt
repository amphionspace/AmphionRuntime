package com.amphion.dingqiao.demo

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** A bounded processing lease for explicit instrumentation; vendor real-time behavior is measured. */
class ThermalQualificationService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private var owner: Lease? = null
    private var wakeLock: PowerManager.WakeLock? = null
    private val expire = Runnable {
        owner?.cancel("service_deadline")
        stopSelf()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Attachment and failure cleanup share LOCK: a late start cannot acquire a released lease.
        val lease = synchronized(LOCK) {
            active?.takeIf { it.token == intent?.getStringExtra(TOKEN) }?.also {
                owner = it
                it.attached = true
            }
        }
        if (lease == null) {
            // A stale notification must not stop the service owned by a newer run.
            if (owner == null) stopSelf(startId)
            return START_NOT_STICKY
        }
        if (intent?.action == CANCEL || lease.closeRequested.get() || lease.cancellation != null) {
            lease.cancel(if (intent?.action == CANCEL) "notification_cancel" else "service_start_cancelled")
            lease.started.countDown()
            stopSelf()
            return START_NOT_STICKY
        }
        if (wakeLock != null) return START_NOT_STICKY
        try {
            val manager = getSystemService(NotificationManager::class.java)
            if (Build.VERSION.SDK_INT >= 26) {
                manager.createNotificationChannel(NotificationChannel(
                    CHANNEL, "Thermal qualification", NotificationManager.IMPORTANCE_LOW,
                ))
            }
            val cancelIntent = PendingIntent.getService(this, 0,
                Intent(this, ThermalQualificationService::class.java)
                    .setAction(CANCEL).setData(Uri.parse("amphion-thermal://lease/${lease.token}"))
                    .putExtra(TOKEN, lease.token),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            @Suppress("DEPRECATION")
            val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL)
                else Notification.Builder(this)
            val notification = builder.setSmallIcon(android.R.drawable.ic_dialog_info)
                .setContentTitle("ASR thermal qualification")
                .setContentText("Processing a fixed local audio window")
                .setOngoing(true)
                .addAction(Notification.Action.Builder(null, "Cancel", cancelIntent).build())
                .build()
            startForeground(NOTIFICATION, notification)
            val hold = getSystemService(PowerManager::class.java)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "$packageName:thermal-qualification")
            wakeLock = hold
            hold.setReferenceCounted(false)
            hold.acquire(lease.timeoutMs)
            handler.postDelayed(expire, lease.timeoutMs)
            lease.started.countDown()
        } catch (_: Throwable) {
            lease.cancel("service_start_failed")
            lease.started.countDown()
            stopSelf()
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        val lease = owner
        // Stop accepting PCM before dropping the processing lifecycle/wake lock on cancellation.
        if (lease != null && !lease.closeRequested.get()) lease.cancel("service_destroyed")
        handler.removeCallbacks(expire)
        try {
            wakeLock?.let { if (it.isHeld) it.release() }
        } catch (_: Throwable) {
            lease?.cleanupFailed("wake_lock_release_failed")
        } finally {
            wakeLock = null
        }
        try {
            stopForeground(STOP_FOREGROUND_REMOVE)
        } catch (_: Throwable) {
            lease?.cleanupFailed("foreground_release_failed")
        } finally {
            if (lease != null) {
                synchronized(LOCK) {
                    // A cleanup failure blocks a new lease until the process is explicitly reset.
                    if (active === lease && lease.cleanupFailure == null) active = null
                    lease.started.countDown()
                    lease.released.countDown()
                }
            }
            owner = null
            super.onDestroy()
        }
    }

    class Lease internal constructor(private val context: Context, internal val timeoutMs: Long) : AutoCloseable {
        internal val token = UUID.randomUUID().toString()
        internal val started = CountDownLatch(1)
        internal val released = CountDownLatch(1)
        internal val closeRequested = AtomicBoolean(false)
        internal var attached = false // Only accessed under LOCK.
        @Volatile var cancellation: String? = null
            private set
        @Volatile var cleanupFailure: String? = null
            private set
        private var cancellationAction: (() -> Unit)? = null
        val isReleased: Boolean get() = released.count == 0L

        /** Register once, immediately after creating the SDK session. Handles cancellation races. */
        fun setCancellationAction(action: () -> Unit) {
            val alreadyCancelled = synchronized(this) {
                check(cancellationAction == null)
                cancellationAction = action
                cancellation != null
            }
            if (alreadyCancelled) invokeCancellation(action)
        }

        internal fun cancel(reason: String) {
            val action = synchronized(this) {
                if (cancellation != null) return
                cancellation = reason
                cancellationAction
            }
            if (action != null) invokeCancellation(action)
        }

        private fun invokeCancellation(action: () -> Unit) {
            try { action() } catch (_: Throwable) { cleanupFailed("cancel_action_failed") }
        }

        @Synchronized internal fun cleanupFailed(reason: String) {
            if (cleanupFailure == null) cleanupFailure = reason
        }

        override fun close() {
            check(Looper.myLooper() != Looper.getMainLooper()) { "lease close requires a worker thread" }
            closeRequested.set(true)
            synchronized(LOCK) {
                if (active === this && !isReleased) {
                    context.stopService(Intent(context, ThermalQualificationService::class.java))
                    // No service ever attached, so there are no owned platform resources to release.
                    if (!attached) {
                        active = null
                        started.countDown()
                        released.countDown()
                    }
                }
            }
            check(released.await(10, TimeUnit.SECONDS)) { "thermal service release timeout" }
            check(cleanupFailure == null) { "thermal service cleanup failed" }
        }
    }

    companion object {
        private const val CHANNEL = "thermal-qualification"
        private const val NOTIFICATION = 52103
        private const val TOKEN = "owner_token"
        private const val CANCEL = "com.amphion.dingqiao.demo.THERMAL_CANCEL"
        private val LOCK = Any()
        private var active: Lease? = null

        /** No affinity/frequency changes, screen wake lock, or battery-optimization exemption. */
        fun acquire(context: Context, timeoutMs: Long): Lease {
            check(Looper.myLooper() != Looper.getMainLooper()) { "lease acquire requires a worker thread" }
            require(timeoutMs in 1_000L..4_200_000L)
            val app = context.applicationContext
            val lease = Lease(app, timeoutMs)
            synchronized(LOCK) {
                check(active == null) { "another thermal test owns the service" }
                active = lease
            }
            try {
                val intent = Intent(app, ThermalQualificationService::class.java).putExtra(TOKEN, lease.token)
                if (Build.VERSION.SDK_INT >= 26) app.startForegroundService(intent) else app.startService(intent)
                check(lease.started.await(15, TimeUnit.SECONDS)) { "thermal service start timeout" }
                check(lease.cancellation == null && !lease.isReleased) { "thermal service failed to start" }
                return lease
            } catch (failure: Throwable) {
                lease.closeRequested.set(true)
                lease.cancel("service_acquire_failed")
                try { lease.close() } catch (cleanup: Throwable) { failure.addSuppressed(cleanup) }
                throw failure
            }
        }
    }
}
