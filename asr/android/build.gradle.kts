// 顶层 build 文件：仅声明 plugin 版本，不在这里 apply
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.android.library) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.dokka) apply false
}

val amphionRuntimeVersion = providers.gradleProperty("AMPHION_RUNTIME_VERSION").get()
val amphionRuntimeVersionParts = amphionRuntimeVersion.substringBefore('-').split('.').map {
    it.toIntOrNull() ?: error("AMPHION_RUNTIME_VERSION must use numeric SemVer: $amphionRuntimeVersion")
}
require(amphionRuntimeVersionParts.size == 3) {
    "AMPHION_RUNTIME_VERSION must contain major.minor.patch: $amphionRuntimeVersion"
}
require(amphionRuntimeVersionParts[1] in 0..99 && amphionRuntimeVersionParts[2] in 0..99) {
    "AMPHION_RUNTIME_VERSION minor and patch must fit two digits: $amphionRuntimeVersion"
}
extra["amphionRuntimeVersionName"] = amphionRuntimeVersion
extra["amphionRuntimeVersionCode"] =
    amphionRuntimeVersionParts[0] * 10_000 +
        amphionRuntimeVersionParts[1] * 100 +
        amphionRuntimeVersionParts[2]

tasks.register("clean", Delete::class) {
    delete(rootProject.layout.buildDirectory)
}
