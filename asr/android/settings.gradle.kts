// 国内网络下 services.gradle.org / dl.google.com 常因代理出现 SSL 握手失败；
// 镜像放前面，官方源作回退。
pluginManagement {
    repositories {
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/central") }
        maven { url = uri("https://maven.aliyun.com/repository/gradle-plugin") }
        google {
            content {
                includeGroupByRegex("com\\.android.*")
                includeGroupByRegex("com\\.google.*")
                includeGroupByRegex("androidx.*")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/central") }
        google()
        mavenCentral()
    }
}

rootProject.name = "AmphionRuntime"

include(":sdk")
include(":sdk-police")
include(":sdk-dingqiao")
include(":samples:public-demo")
include(":samples:mini-demo")
include(":samples:internal-eval")
include(":samples:dingqiao-demo")
