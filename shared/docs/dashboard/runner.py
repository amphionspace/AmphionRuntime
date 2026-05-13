#!/usr/bin/env python3
"""shared/docs/dashboard/runner.py

月度跨端联合工程指标 dashboard 生成器。

注意：识别正确性（WER / CER）由上游 scripts/benchmark/ 统一出报告，下游不重复造轮子。
本 dashboard 只追踪三类工程指标：

1. 端侧启动延迟（Android / iOS engine init）
2. 服务端 RTF / 并发 / 内存 / first-partial 延迟（来自 server bench）
3. 端侧 crash 率（Android Bugly/Crashlytics、iOS Crashlytics/Sentry 预拉 JSON）

设计目标：
- 可在 CI 上独立执行，单文件，无第三方依赖（标准库即可）
- 三端 / server / 崩溃源 各自抽象成独立 collector，方便单测与替换
- 缺失数据用 `-` 占位，永远不让模板崩溃；同时把状态标成 unknown

使用例：
    python shared/docs/dashboard/runner.py \
        --month 2026-05 \
        --android-aar artifacts/asr-sdk-1.1.0.aar \
        --ios-xcframework artifacts/SherpaAsrSdk-1.1.0.xcframework \
        --server-image your-registry/asr-service:1.1.0 \
        --bench-target localhost:50051 \
        --upstream-wer-report-url 'https://internal.example/asr/wer/2026-05.html' \
        --out shared/docs/dashboard/trends/reports/2026-05.md
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TPL = Path(__file__).resolve().parent / "templates" / "monthly.md.tpl"
DEFAULT_TRENDS = Path(__file__).resolve().parent / "trends"


@dataclass
class StartupStats:
    cold_p50: float = float("nan")
    cold_p95: float = float("nan")
    hot_p50: float = float("nan")
    hot_p95: float = float("nan")


@dataclass
class CrashStats:
    rate: float = float("nan")
    top: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ServerBench:
    max_concurrency: int = 0
    rtf_p50: float = float("nan")
    rtf_p99: float = float("nan")
    mem_peak_mib: float = float("nan")
    first_partial_p95: float = float("nan")
    error_rate: float = float("nan")
    error_top: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class MonthlyReport:
    month: str
    prev_month: str
    generated_at: str
    android_startup: StartupStats = field(default_factory=StartupStats)
    ios_startup: StartupStats = field(default_factory=StartupStats)
    android_crash: CrashStats = field(default_factory=CrashStats)
    ios_crash: CrashStats = field(default_factory=CrashStats)
    server_bench: ServerBench = field(default_factory=ServerBench)
    upstream_wer_report_url: str = "-"
    model_id: str = "-"
    model_version: str = "-"
    android_sdk_version: str = "-"
    android_sdk_sha: str = "-"
    ios_sdk_version: str = "-"
    ios_sdk_sha: str = "-"
    server_image: str = "-"
    server_image_digest: str = "-"
    p0_p1_list: List[str] = field(default_factory=list)
    followups: List[str] = field(default_factory=list)
    next_month_plan: List[str] = field(default_factory=list)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--month", required=True, help="YYYY-MM")
    p.add_argument("--android-aar", type=Path, help="Android AAR artifact for startup smoke run")
    p.add_argument("--ios-xcframework", type=Path, help="iOS xcframework artifact for startup smoke run")
    p.add_argument("--server-image", default=None, help="Server docker image; if empty, server bench skipped")
    p.add_argument("--bench-target", default=None, help="host:port for server bench script")
    p.add_argument("--regression-set", type=Path, default=REPO_ROOT / "shared" / "regression-set",
                   help="path to shared regression set (used as PCM source by server bench)")
    p.add_argument("--out", type=Path, required=True, help="output markdown report path")
    p.add_argument("--trends-dir", type=Path, default=DEFAULT_TRENDS,
                   help="directory containing rtf.csv / crash.csv / startup.csv")
    p.add_argument("--template", type=Path, default=DEFAULT_TPL,
                   help="markdown template path")
    p.add_argument("--android-startup-runner", default=None,
                   help="Optional shell command to collect Android startup latency; must print json to stdout")
    p.add_argument("--ios-startup-runner", default=None,
                   help="Optional shell command to collect iOS startup latency; must print json to stdout")
    p.add_argument("--bench-runner", default=None,
                   help="Optional shell command to run server bench; must print json to stdout")
    p.add_argument("--android-crash-source", default=None,
                   help="path to JSON file pre-fetched from Bugly/Crashlytics")
    p.add_argument("--ios-crash-source", default=None,
                   help="path to JSON file pre-fetched from Crashlytics/Sentry")
    p.add_argument("--upstream-wer-report-url", default=None,
                   help="URL to the upstream sherpa-onnx WER/CER report for this month's model")
    p.add_argument("--dry-run", action="store_true", help="Skip external commands, generate empty report")
    return p.parse_args(argv)


def shell_json(cmd: str) -> Dict[str, Any]:
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(f"[runner] command failed (rc={proc.returncode}): {cmd}\nstderr:\n{proc.stderr}\n")
        return {}
    out = proc.stdout.strip()
    if not out:
        sys.stderr.write(f"[runner] command produced empty stdout: {cmd}\n")
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"[runner] command stdout not valid json: {cmd}\nerror={e}\nstdout snippet:\n{out[:400]}\n")
        return {}


def parse_startup(payload: Dict[str, Any]) -> StartupStats:
    if not payload:
        return StartupStats()
    s = payload.get("startup") or payload
    return StartupStats(
        cold_p50=float(s.get("cold_p50_ms", float("nan"))),
        cold_p95=float(s.get("cold_p95_ms", float("nan"))),
        hot_p50=float(s.get("hot_p50_ms", float("nan"))),
        hot_p95=float(s.get("hot_p95_ms", float("nan"))),
    )


def parse_crash(payload: Dict[str, Any]) -> CrashStats:
    if not payload:
        return CrashStats()
    return CrashStats(
        rate=float(payload.get("crash_rate", float("nan"))),
        top=list(payload.get("top", []) or [])[:5],
    )


def parse_server_bench(payload: Dict[str, Any]) -> ServerBench:
    if not payload:
        return ServerBench()
    rtf = payload.get("rtf", {})
    fp = payload.get("first_partial_ms", {})
    err = payload.get("error", {})
    return ServerBench(
        max_concurrency=int(payload.get("max_concurrency", 0) or 0),
        rtf_p50=float(rtf.get("p50", float("nan"))),
        rtf_p99=float(rtf.get("p99", float("nan"))),
        mem_peak_mib=float(payload.get("mem_peak_mib", float("nan"))),
        first_partial_p95=float(fp.get("p95", float("nan"))),
        error_rate=float(err.get("rate", float("nan"))),
        error_top=list(err.get("top", []) or [])[:5],
    )


def fmt_pct(v: float, digits: int = 2) -> str:
    if v != v:
        return "-"
    return f"{v:.{digits}f}%"


def fmt_num(v: float, digits: int = 3) -> str:
    if v != v:
        return "-"
    return f"{v:.{digits}f}"


def fmt_int(v: int) -> str:
    return str(v) if v else "-"


def fmt_delta(curr: float, prev: float, kind: str = "pct") -> str:
    if curr != curr or prev != prev:
        return "-"
    delta = curr - prev
    if kind == "pct":
        sign = "+" if delta >= 0 else ""
        return f"{sign}{delta:.2f}pp"
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.3f}"


def status(curr: float, threshold: float, lower_is_better: bool = True) -> str:
    if curr != curr or threshold != threshold:
        return "unknown"
    if not lower_is_better and curr <= 0:
        return "unknown"
    if lower_is_better:
        if curr <= threshold:
            return "OK"
        if curr <= threshold * 1.1:
            return "WARN"
        return "FAIL"
    if curr >= threshold:
        return "OK"
    if curr >= threshold * 0.9:
        return "WARN"
    return "FAIL"


def append_csv(csv_path: Path, header: List[str], row: Dict[str, Any]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if is_new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in header})


def previous_month(month: str) -> str:
    y, m = map(int, month.split("-"))
    if m == 1:
        return f"{y - 1:04d}-12"
    return f"{y:04d}-{m - 1:02d}"


def load_prev_csv_row(csv_path: Path, prev_month: str) -> Dict[str, str]:
    if not csv_path.exists():
        return {}
    with csv_path.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        rows = [row for row in r if row.get("month") == prev_month]
    return rows[-1] if rows else {}


def render_table_rows(items: Iterable[Dict[str, Any]], cols: List[str]) -> str:
    lines = []
    for it in items:
        cells = [str(it.get(c, "-")) for c in cols]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) if lines else "| - | - | - | - | - |"


def collect_android_startup(args: argparse.Namespace) -> StartupStats:
    if args.dry_run or not args.android_startup_runner:
        return StartupStats()
    return parse_startup(shell_json(args.android_startup_runner))


def collect_ios_startup(args: argparse.Namespace) -> StartupStats:
    if args.dry_run or not args.ios_startup_runner:
        return StartupStats()
    return parse_startup(shell_json(args.ios_startup_runner))


def collect_server_bench(args: argparse.Namespace) -> ServerBench:
    if args.dry_run:
        return ServerBench()
    if args.bench_runner:
        return parse_server_bench(shell_json(args.bench_runner))
    if not args.bench_target:
        return ServerBench()
    bench_script = REPO_ROOT / "server" / "asr-service" / "bench" / "bench_concurrent.py"
    if not bench_script.exists():
        sys.stderr.write(f"[runner] bench script missing: {bench_script}\n")
        return ServerBench()
    out = REPO_ROOT / "build" / "dashboard" / f"bench-{args.month}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = (
        f"python {bench_script} --target {args.bench_target} "
        f"--regression-set {args.regression_set} --json-out {out}"
    )
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        sys.stderr.write(f"[runner] bench command failed: {cmd}\nstderr:\n{proc.stderr}\n")
        return ServerBench()
    if not out.exists():
        return ServerBench()
    return parse_server_bench(json.loads(out.read_text(encoding="utf-8")))


def collect_crash(path: Optional[str]) -> CrashStats:
    if not path:
        return CrashStats()
    p = Path(path)
    if not p.exists():
        sys.stderr.write(f"[runner] crash source missing: {p}\n")
        return CrashStats()
    return parse_crash(json.loads(p.read_text(encoding="utf-8")))


def render_report(report: MonthlyReport, prev_csv_rows: Dict[str, Dict[str, str]], template: Path) -> str:
    tpl = template.read_text(encoding="utf-8")

    def prev_get(table: str, key: str) -> float:
        row = prev_csv_rows.get(table) or {}
        try:
            return float(row[key])
        except Exception:
            return float("nan")

    rtf_single = report.server_bench.rtf_p50
    rtf_p95 = report.server_bench.rtf_p99

    rtf_single_prev = prev_get("rtf", "rtf_p50")
    rtf_p95_prev = prev_get("rtf", "rtf_p99")
    crash_android_prev = prev_get("crash", "android")
    crash_ios_prev = prev_get("crash", "ios")
    svr_err_prev = prev_get("rtf", "error_rate")
    android_cold_p95_prev = prev_get("startup", "android_cold_p95")
    ios_cold_p95_prev = prev_get("startup", "ios_cold_p95")

    crash_top_table = render_table_rows(
        [
            {**c, "endpoint": "Android"}
            for c in report.android_crash.top
        ]
        + [
            {**c, "endpoint": "iOS"}
            for c in report.ios_crash.top
        ],
        ["endpoint", "issue", "users", "owner", "status"],
    )
    svr_err_table = render_table_rows(
        report.server_bench.error_top,
        ["code", "name", "ratio", "owner", "status"],
    )

    mapping: Dict[str, str] = {
        "MONTH": report.month,
        "PREV_MONTH": report.prev_month,
        "GENERATED_AT": report.generated_at,
        "UPSTREAM_WER_REPORT_URL": report.upstream_wer_report_url,
        "RTF_SINGLE": fmt_num(rtf_single),
        "RTF_SINGLE_PREV": fmt_num(rtf_single_prev),
        "RTF_SINGLE_DELTA": fmt_delta(rtf_single, rtf_single_prev, kind="num"),
        "RTF_SINGLE_STATUS": status(rtf_single, 0.35),
        "RTF_P95": fmt_num(rtf_p95),
        "RTF_P95_PREV": fmt_num(rtf_p95_prev),
        "RTF_P95_DELTA": fmt_delta(rtf_p95, rtf_p95_prev, kind="num"),
        "RTF_P95_STATUS": status(rtf_p95, 0.5),
        "ANDROID_COLD_P95_DELTA": fmt_delta(report.android_startup.cold_p95, android_cold_p95_prev, kind="num"),
        "IOS_COLD_P95_DELTA": fmt_delta(report.ios_startup.cold_p95, ios_cold_p95_prev, kind="num"),
        "CRASH_ANDROID": fmt_pct(report.android_crash.rate),
        "CRASH_ANDROID_PREV": fmt_pct(crash_android_prev),
        "CRASH_ANDROID_DELTA": fmt_delta(report.android_crash.rate, crash_android_prev),
        "CRASH_ANDROID_STATUS": status(report.android_crash.rate, 0.05),
        "CRASH_IOS": fmt_pct(report.ios_crash.rate),
        "CRASH_IOS_PREV": fmt_pct(crash_ios_prev),
        "CRASH_IOS_DELTA": fmt_delta(report.ios_crash.rate, crash_ios_prev),
        "CRASH_IOS_STATUS": status(report.ios_crash.rate, 0.05),
        "SVR_ERROR_RATE": fmt_pct(report.server_bench.error_rate),
        "SVR_ERROR_RATE_PREV": fmt_pct(svr_err_prev),
        "SVR_ERROR_RATE_DELTA": fmt_delta(report.server_bench.error_rate, svr_err_prev),
        "SVR_ERROR_RATE_STATUS": status(report.server_bench.error_rate, 0.1),
        "ANDROID_COLD_P50": fmt_num(report.android_startup.cold_p50, 0),
        "ANDROID_COLD_P95": fmt_num(report.android_startup.cold_p95, 0),
        "ANDROID_HOT_P50": fmt_num(report.android_startup.hot_p50, 0),
        "ANDROID_HOT_P95": fmt_num(report.android_startup.hot_p95, 0),
        "IOS_COLD_P50": fmt_num(report.ios_startup.cold_p50, 0),
        "IOS_COLD_P95": fmt_num(report.ios_startup.cold_p95, 0),
        "IOS_HOT_P50": fmt_num(report.ios_startup.hot_p50, 0),
        "IOS_HOT_P95": fmt_num(report.ios_startup.hot_p95, 0),
        "SVR_MAX_CONCURRENCY": fmt_int(report.server_bench.max_concurrency),
        "SVR_MAX_CONCURRENCY_TARGET": "16",
        "SVR_MAX_CONCURRENCY_STATUS": status(float(report.server_bench.max_concurrency), 16.0, lower_is_better=False),
        "SVR_RTF_P50": fmt_num(report.server_bench.rtf_p50),
        "SVR_RTF_P99": fmt_num(report.server_bench.rtf_p99),
        "SVR_RTF_TARGET": "0.35",
        "SVR_RTF_P50_STATUS": status(report.server_bench.rtf_p50, 0.35),
        "SVR_RTF_P99_STATUS": status(report.server_bench.rtf_p99, 0.5),
        "SVR_MEM_PEAK": fmt_num(report.server_bench.mem_peak_mib, 0),
        "SVR_MEM_TARGET": "2048",
        "SVR_MEM_STATUS": status(report.server_bench.mem_peak_mib, 2048.0),
        "SVR_FIRST_PARTIAL_P95": fmt_num(report.server_bench.first_partial_p95, 0),
        "SVR_FIRST_PARTIAL_TARGET": "500",
        "SVR_FIRST_PARTIAL_STATUS": status(report.server_bench.first_partial_p95, 500.0),
        "CRASH_TOP_TABLE": crash_top_table,
        "SVR_ERROR_TOP_TABLE": svr_err_table,
        "P0_P1_LIST": "\n".join(f"- {x}" for x in report.p0_p1_list) or "- 无",
        "FOLLOWUPS": "\n".join(f"- {x}" for x in report.followups) or "- 无",
        "NEXT_MONTH_PLAN": "\n".join(f"- {x}" for x in report.next_month_plan) or "- 待补充",
        "MODEL_ID": report.model_id,
        "MODEL_VERSION": report.model_version,
        "ANDROID_SDK_VERSION": report.android_sdk_version,
        "ANDROID_SDK_SHA": report.android_sdk_sha,
        "IOS_SDK_VERSION": report.ios_sdk_version,
        "IOS_SDK_SHA": report.ios_sdk_sha,
        "SERVER_IMAGE": report.server_image,
        "SERVER_IMAGE_DIGEST": report.server_image_digest,
        "HOSTNAME": socket.gethostname(),
        "OS_INFO": f"{os.name}-{sys.platform}",
    }
    out = tpl
    for k, v in mapping.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    month = args.month
    prev = previous_month(month)

    android_startup = collect_android_startup(args)
    ios_startup = collect_ios_startup(args)
    server_bench = collect_server_bench(args)
    android_crash = collect_crash(args.android_crash_source)
    ios_crash = collect_crash(args.ios_crash_source)

    report = MonthlyReport(
        month=month,
        prev_month=prev,
        generated_at=dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ"),
        android_startup=android_startup,
        ios_startup=ios_startup,
        android_crash=android_crash,
        ios_crash=ios_crash,
        server_bench=server_bench,
        upstream_wer_report_url=args.upstream_wer_report_url or "-",
        android_sdk_version=str(args.android_aar.name) if args.android_aar else "-",
        ios_sdk_version=str(args.ios_xcframework.name) if args.ios_xcframework else "-",
        server_image=args.server_image or "-",
    )

    trends_dir = args.trends_dir
    prev_rows = {
        "rtf": load_prev_csv_row(trends_dir / "rtf.csv", prev),
        "crash": load_prev_csv_row(trends_dir / "crash.csv", prev),
        "startup": load_prev_csv_row(trends_dir / "startup.csv", prev),
    }

    rendered = render_report(report, prev_rows, args.template)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")

    append_csv(
        trends_dir / "rtf.csv",
        ["month", "max_concurrency", "rtf_p50", "rtf_p99", "first_partial_p95",
         "mem_peak_mib", "error_rate"],
        {
            "month": month,
            "max_concurrency": server_bench.max_concurrency,
            "rtf_p50": server_bench.rtf_p50,
            "rtf_p99": server_bench.rtf_p99,
            "first_partial_p95": server_bench.first_partial_p95,
            "mem_peak_mib": server_bench.mem_peak_mib,
            "error_rate": server_bench.error_rate,
        },
    )
    append_csv(
        trends_dir / "crash.csv",
        ["month", "android", "ios"],
        {
            "month": month,
            "android": android_crash.rate,
            "ios": ios_crash.rate,
        },
    )
    append_csv(
        trends_dir / "startup.csv",
        ["month",
         "android_cold_p50", "android_cold_p95", "android_hot_p50", "android_hot_p95",
         "ios_cold_p50", "ios_cold_p95", "ios_hot_p50", "ios_hot_p95"],
        {
            "month": month,
            "android_cold_p50": android_startup.cold_p50,
            "android_cold_p95": android_startup.cold_p95,
            "android_hot_p50": android_startup.hot_p50,
            "android_hot_p95": android_startup.hot_p95,
            "ios_cold_p50": ios_startup.cold_p50,
            "ios_cold_p95": ios_startup.cold_p95,
            "ios_hot_p50": ios_startup.hot_p50,
            "ios_hot_p95": ios_startup.hot_p95,
        },
    )

    sys.stdout.write(str(args.out) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
