"""Shared, versioned contract for persisted Harmony release evidence."""

SCHEMA_VERSION = 1
HARMONY_RELEASE_MODES = (
    "burst",
    "paced",
    "vad-begin",
    "vad-begin-silence",
    "voiceprint",
    "voiceprint-fallback",
    "voiceprint-vad-begin",
    "voiceprint-vad-begin-idle",
    "cancel",
    "cancel-full",
    "recreate",
    "reconfigure",
    "max-duration",
    "edge",
    "reentrant",
    "start-cancel",
    "start-write",
    "start-write-reload",
    "speaker-vad-onstart",
    "callback-api-reentrant",
    "endpoint-reentrant",
    "finish-shutdown",
    "user-sequence",
    "numeric-edge",
)
MIN_LONG_RUN_SECONDS = 60.0
