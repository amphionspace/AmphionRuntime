package com.amphion.police

/** Hidden experiment profile used only while pruning the built-in police hotword budget. */
enum class PoliceHotwordProfile(val wireValue: String) {
    FULL("full"),
    NONE("none"),
    ;

    companion object {
        const val EXPERIMENTAL_PARAM: String = "__experimentalPoliceHotwordProfile"

        fun parse(raw: Any?): PoliceHotwordProfile = when (raw) {
            null, FULL.wireValue -> FULL
            NONE.wireValue -> NONE
            else -> throw IllegalArgumentException(
                "$EXPERIMENTAL_PARAM must be full or none, got $raw",
            )
        }
    }
}
