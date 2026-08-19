// CI runner 直接使用官方源，避免冷缓存构建依赖单个镜像的可用性；
// 国内本地开发仍将镜像放前面，官方源作回退。
pluginManagement {
    repositories {
        if (System.getenv("CI").equals("true", ignoreCase = true)) {
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
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/central") }
        maven { url = uri("https://maven.aliyun.com/repository/gradle-plugin") }
        if (!System.getenv("CI").equals("true", ignoreCase = true)) {
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
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        if (System.getenv("CI").equals("true", ignoreCase = true)) {
            google()
            mavenCentral()
        }
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/central") }
        if (!System.getenv("CI").equals("true", ignoreCase = true)) {
            google()
            mavenCentral()
        }
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
