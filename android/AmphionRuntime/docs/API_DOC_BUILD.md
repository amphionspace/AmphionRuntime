# 生成 API 文档（Dokka）

本 SDK 使用 [Dokka 1.9.20](https://kotlinlang.org/docs/dokka-introduction.html) 生成 HTML API 文档。

## 一、本地生成

确保 Gradle wrapper 已经初始化（参考根目录 `init_gradle_wrapper.sh`）：

```bash
cd android/AmphionRuntime
bash init_gradle_wrapper.sh    # 仅首次需要
```

生成 HTML 文档：

```bash
./gradlew :sdk:dokkaHtml
```

产物路径：

```
sdk/build/dokka/html/
├── index.html               # 文档入口
├── navigation.html
├── -asr--s-d-k/             # 包文档
└── ...
```

直接用浏览器打开 `sdk/build/dokka/html/index.html` 即可查看。

## 二、文档范围

`sdk/build.gradle.kts` 中的 Dokka 配置已经做了以下过滤：

| 范围 | 是否进入文档 |
| --- | --- |
| `com.amphion.asr.*` 公开类型 | 是 |
| `com.amphion.asr.internal.*` | 否（被 perPackageOption 抑制） |
| `com.k2fsa.sherpa.onnx.*` | 否（属于上游模板，不暴露给客户） |
| internal 可见性的成员 | 否（仅 PUBLIC） |
| 继承自 Object/Any 的方法 | 否（suppressInheritedMembers） |

如果想打开 internal 文档辅助调试，临时把 `sdk/build.gradle.kts` 的 `documentedVisibilities` 加上 `INTERNAL`：

```kotlin
documentedVisibilities.set(setOf(
    org.jetbrains.dokka.DokkaConfiguration.Visibility.PUBLIC,
    org.jetbrains.dokka.DokkaConfiguration.Visibility.INTERNAL,
))
```

## 三、发布到内网

最简单的发布方式：把 `sdk/build/dokka/html/` 整个目录拷到任意静态文件服务器（nginx / Aliyun OSS 静态网站 / GitHub Pages）。

如果你用 GitHub Pages：

```bash
./gradlew :sdk:dokkaHtml
git checkout gh-pages
rm -rf .                                          # 注意当前在 gh-pages 分支
cp -r sdk/build/dokka/html/* .
git add .
git commit -m "docs(api): 0.1.0"
git push origin gh-pages
```

之后在你的 README 链一份：

```
https://amphion.github.io/amphion-runtime/
```

## 四、与版本号联动

每次发版前同步执行：

```bash
./gradlew :sdk:dokkaHtml :sdk:assembleRelease :sdk:publishReleasePublicationToLocalFileRepoRepository
```

把 AAR、Maven artifacts、API 文档一起推到内部分发系统即可。

## 五、常见问题

Q：`./gradlew :sdk:dokkaHtml` 报 `Cannot resolve plugin: org.jetbrains.dokka:1.9.20`
A：先确认 Gradle 能联通 mavenCentral；如果有公司代理把它加到 `~/.gradle/init.d/repos.gradle`。

Q：生成的 HTML 中文显示乱码
A：Dokka 默认 UTF-8，乱码一般是浏览器编码问题；用 Chrome 直接打开 file:// 通常没问题。如果是从 nginx 服务，加 `default_type text/html; charset utf-8;`。

Q：能否生成 markdown 而不是 HTML？
A：可以，把 `dokkaHtml` 换成 `dokkaGfm`。但 markdown 输出的链接结构不太适合直接放到 README，建议保留 HTML。
