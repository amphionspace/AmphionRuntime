package com.amphion.police

/** Hidden experiment profile used only while pruning the built-in police hotword budget. */
enum class PoliceHotwordProfile(val wireValue: String) {
    FULL("full"),
    PRUNE_UI30("prune_ui30"),
    NONE("none"),
    ;

    companion object {
        const val EXPERIMENTAL_PARAM: String = "__experimentalPoliceHotwordProfile"

        fun parse(raw: Any?): PoliceHotwordProfile = when (raw) {
            null, FULL.wireValue -> FULL
            PRUNE_UI30.wireValue -> PRUNE_UI30
            NONE.wireValue -> NONE
            else -> throw IllegalArgumentException(
                "$EXPERIMENTAL_PARAM must be full, prune_ui30 or none, got $raw",
            )
        }
    }
}
