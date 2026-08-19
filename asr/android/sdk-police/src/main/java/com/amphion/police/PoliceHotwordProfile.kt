package com.amphion.police

/** Hidden experiment profile used only while pruning the built-in police hotword budget. */
enum class PoliceHotwordProfile(val wireValue: String) {
    FULL("full"),
    PRUNE_UI28("prune_ui28"),
    NONE("none"),
    ;

    companion object {
        const val EXPERIMENTAL_PARAM: String = "__experimentalPoliceHotwordProfile"

        /**
         * Profile compiled into this SDK artifact. Delivery builds remain [FULL] unless the
         * validated Gradle property `policeDefaultHotwordProfile=prune_ui28` is supplied.
         */
        fun defaultProfile(): PoliceHotwordProfile = when (BuildConfig.DEFAULT_HOTWORD_PROFILE) {
            FULL.wireValue -> FULL
            PRUNE_UI28.wireValue -> PRUNE_UI28
            else -> error(
                "invalid compiled police hotword profile: ${BuildConfig.DEFAULT_HOTWORD_PROFILE}",
            )
        }

        fun parse(raw: Any?): PoliceHotwordProfile = when (raw) {
            null -> defaultProfile()
            FULL.wireValue -> FULL
            PRUNE_UI28.wireValue -> PRUNE_UI28
            NONE.wireValue -> NONE
            else -> throw IllegalArgumentException(
                "$EXPERIMENTAL_PARAM must be full, prune_ui28 or none, got $raw",
            )
        }
    }
}
