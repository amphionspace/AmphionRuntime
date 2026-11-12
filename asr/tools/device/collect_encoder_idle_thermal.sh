#!/system/bin/sh
# Read-only device sampling, apart from this run's output and its cooperative ABORT marker.
# No settings, whitelist, frequency, affinity, UI, application-start, or process-kill operations.
set -u
RUN_ID=${1:-}
case "$RUN_ID" in ''|*[!A-Za-z0-9._-]*|.*|-*) echo 'invalid run id' >&2; exit 64;; esac
[ "${#RUN_ID}" -le 96 ] || exit 64
PKG=com.amphion.dingqiao.demo
OUT_BASE=${THERMAL_OUT_BASE:-/data/local/tmp/amphion-thermal-qualification}
case "$OUT_BASE" in /data/local/tmp/*) ;; *) echo 'output base must be under /data/local/tmp' >&2; exit 64;; esac
APP_REPORT=/sdcard/Android/data/$PKG/files/thermal_qualification/$RUN_ID
OUT=$OUT_BASE/$RUN_ID
INTERVAL=${INTERVAL_SECONDS:-10}
WAIT_START=${WAIT_START_SECONDS:-300}
MAX_SECONDS=${MAX_RUN_SECONDS:-420}
EXPECTED_USB=${EXPECTED_USB:-0}
SHELL_GUARD_M=${SHELL_GUARD_M:-50000}
uint() { case "$1" in ''|*[!0-9]*) return 1;; *) return 0;; esac; }
sint() { case "$1" in -*) uint "${1#-}";; *) uint "$1";; esac; }
for value in "$INTERVAL" "$WAIT_START" "$MAX_SECONDS" "$EXPECTED_USB" "$SHELL_GUARD_M"; do
    uint "$value" || { echo 'invalid numeric setting' >&2; exit 64; }
done
[ "$INTERVAL" -ge 1 ] && [ "$INTERVAL" -le 60 ] || exit 64
[ "$WAIT_START" -ge 1 ] && [ "$WAIT_START" -le 600 ] || exit 64
[ "$MAX_SECONDS" -ge 1 ] && [ "$MAX_SECONDS" -le 4200 ] || exit 64
[ "$EXPECTED_USB" -le 1 ] || exit 64
[ "$SHELL_GUARD_M" -ge 40000 ] && [ "$SHELL_GUARD_M" -le 60000 ] || exit 64
mkdir -p "$OUT_BASE" || exit 73
mkdir "$OUT" || { echo 'run directory exists; preserve it and choose a new id' >&2; exit 73; }
read_value() {
    value_read=
    { IFS= read -r value_read < "$1"; } 2>/dev/null
    printf '%s' "$value_read"
}
mono_s() { IFS=' ' read -r uptime_value ignored < /proc/uptime; printf '%s' "${uptime_value%%.*}"; }
mono_ms() { awk '{ printf "%.0f", $1 * 1000; exit }' /proc/uptime; }
invalid=0
samples=0
previous_sample=-1
cpu_samples=0
first_cpu_ms=-1
last_cpu_ms=-1
last_thermal_dump=-60
start_wait=$(mono_s)
status() { printf '%s\t%s\t%s\n' "$(mono_s)" "$1" "$2" >> "$OUT/status.tsv"; }
mark_invalid() { invalid=1; status INVALID "$1"; }
abort_app() {
    status ABORT_REQUEST "$1"
    if [ -d "$APP_REPORT" ] && [ ! -e "$APP_REPORT/ABORT" ]; then
        (set -C; printf '%s\n' "$1" > "$APP_REPORT/ABORT") 2>/dev/null || status ABORT_WRITE_FAILED "$1"
    fi
}
finish() {
    status RESULT "$1"
    printf '%s\n' "$1" > "$OUT/DONE"
    exit "$2"
}
trap '' HUP
trap 'mark_invalid collector_interrupted; abort_app collector_interrupted; finish INCOMPLETE 130' INT TERM
printf 'mono_s\tevent\tdetail\n' > "$OUT/status.tsv"
printf 'mono_s\tepoch_s\ttype\traw_milli_c\tvalid\treason\n' > "$OUT/thermal.tsv"
printf 'mono_s\tepoch_s\tusb_online\tbattery_capacity\tcurrent_now_raw\tvoltage_now_raw\tcharge_counter_raw\tbattery_temp_deci_c\n' > "$OUT/battery.tsv"
printf 'mono_s\tpolicy\tcur_khz\tmin_khz\tmax_khz\thardware_max_khz\tgovernor\taffected_cpus\n' > "$OUT/cpufreq.tsv"
printf 'mono_s\tpid\ttid\tcomm\tstate\tcpu_ticks\tprocessor\tcpuset\tcpus_allowed_list\n' > "$OUT/threads.tsv"
{
    printf 'run_id=%s\npackage=%s\nexpected_usb=%s\ninterval_seconds=%s\nshell_guard_m=%s\n' "$RUN_ID" "$PKG" "$EXPECTED_USB" "$INTERVAL" "$SHELL_GUARD_M"
    printf 'wait_start_seconds=%s\nmax_run_seconds=%s\ncollector_pid=%s\napp_report=%s\n' "$WAIT_START" "$MAX_SECONDS" "$$" "$APP_REPORT"
    printf 'build_fingerprint='; getprop ro.build.fingerprint
    printf 'clk_tck='; getconf CLK_TCK 2>/dev/null || printf 'unknown\n'
    printf 'Current/voltage/charge_counter are raw; verify vendor units before energy calculations.\n'
    printf 'PASS means collection quality only, never thermal acceptance.\n'
} > "$OUT/metadata.txt"
status WAITING_FOR_START "$APP_REPORT"
while :; do
    app_result=$(read_value "$APP_REPORT/DONE")
    [ -z "$app_result" ] || finish APP_FINISHED_BEFORE_COLLECTION 2
    start_ms=$(read_value "$APP_REPORT/STARTED")
    if uint "$start_ms"; then break; fi
    now=$(mono_s)
    [ "$((now - start_wait))" -lt "$WAIT_START" ] || finish START_TIMEOUT 2
    sleep 1
done
start_s=$((start_ms / 1000))
now=$(mono_s)
[ "$start_s" -le "$now" ] || finish INVALID_START_CLOCK 2
status STARTED "$start_ms"
next_sample=$now

# Report emits flat, compact JSONObject rows; DONE is written after the result row.
# Reject missing/duplicate results, another run, failed cleanup, and impossible clocks.
read_completion() {
    [ "$(read_value "$APP_REPORT/DONE")" = PASS_PROCESSING_ONLY ] || return 1
    completion_ms=$(awk -v run="$RUN_ID" '
        function field(key) {
            if (!match($0, "\"" key "\":[^,}]*")) return ""
            return substr($0, RSTART + length(key) + 3, RLENGTH - length(key) - 3)
        }
        field("event") == "\"result\"" {
            results++
            stamp = field("elapsedRealtimeMs")
            valid = field("runId") == "\"" run "\"" &&
                field("status") == "\"PASS_PROCESSING_ONLY\"" && stamp ~ /^[0-9]+$/ &&
                field("starts") == 1 && field("lasts") == 1 && field("stops") == 1 &&
                field("errors") == 0 && field("callbackOrderValid") == "true" &&
                field("serviceReleased") == "true" && field("monitorTerminated") == "true" &&
                field("cleanupFailures") == "\"\"" && field("serviceCancellation") == "null" &&
                field("serviceCleanupFailure") == "null"
        }
        END { if (results != 1 || !valid) exit 1; print stamp }
    ' "$APP_REPORT/report.jsonl" 2>/dev/null) || return 1
    # /proc/uptime has 10 ms resolution; only the observation clock gets this allowance.
    [ "$completion_ms" -ge "$start_ms" ] && [ "$completion_ms" -le "$(( $(mono_ms) + 9 ))" ]
}

cpu_coverage_ok() {
    cpu_tail_ms=$((completion_ms - last_cpu_ms))
    [ "$cpu_tail_ms" -ge 0 ] || cpu_tail_ms=0
    [ "$cpu_samples" -ge 2 ] && [ "$cpu_tail_ms" -le "$(((INTERVAL + 2) * 1000))" ]
}

sample_threads() {
    cpu_sample_ms=$(mono_ms)
    pid=$(pidof "$PKG" 2>/dev/null)
    readable_tasks=0
    cpu_pid_missing=0
    cpu_unavailable_ms=-1
    cpu_process_exited=0
    if uint "$pid"; then
        for task in /proc/$pid/task/[0-9]*; do
            [ -d "$task" ] || continue
            tid=${task##*/}
            comm=$(read_value "$task/comm")
            cpuset=$(read_value "$task/cpuset")
            allowed=$(awk '$1 == "Cpus_allowed_list:" { print $2 }' "$task/status" 2>/dev/null)
            raw_stat=$(read_value "$task/stat")
            # A thread may exit between directory enumeration and reading its stat file.
            [ -n "$raw_stat" ] || continue
            stat_fields=$(printf '%s\n' "$raw_stat" | awk '{ sub(/^.*\) /, ""); printf "%s\t%s\t%s", $1, $12 + $13, $37 }')
            printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$((cpu_sample_ms / 1000))" "$pid" "$tid" "$comm" "$stat_fields" "$cpuset" "$allowed" >> "$OUT/threads.tsv"
            [ -z "$cpuset" ] || [ -z "$allowed" ] || readable_tasks=$((readable_tasks + 1))
        done
        { printf '=== mono_s=%s pid=%s ===\n' "$((cpu_sample_ms / 1000))" "$pid"; while IFS= read -r line; do printf '%s\n' "$line"; done < "/proc/$pid/cgroup"; } >> "$OUT/cgroup.txt" 2>&1
    else
        cpu_pid_missing=1
    fi
    if [ "$readable_tasks" -gt 0 ]; then
        if [ "$last_cpu_ms" -lt 0 ]; then
            first_cpu_ms=$cpu_sample_ms
            [ "$((first_cpu_ms - start_ms))" -le "$(((INTERVAL + 2) * 1000))" ] || mark_invalid late_first_cpu_sample
        else
            [ "$((cpu_sample_ms - last_cpu_ms))" -le "$(((2 * INTERVAL + 2) * 1000))" ] || mark_invalid cpu_sampling_gap
        fi
        last_cpu_ms=$cpu_sample_ms
        cpu_samples=$((cpu_samples + 1))
    else
        cpu_unavailable_ms=$(mono_ms)
        # Ambiguous PIDs or unreadable live processes are never treated as natural exit.
        if [ -z "$pid" ] || { uint "$pid" && [ ! -d "/proc/$pid" ]; }; then cpu_process_exited=1; fi
    fi
}

sample() {
    sample_now=$(mono_s)
    epoch=$(date +%s)
    if [ "$previous_sample" -lt 0 ]; then
        [ "$((sample_now - start_s))" -le "$((INTERVAL + 2))" ] || mark_invalid late_first_sample
    else
        [ "$((sample_now - previous_sample))" -le "$((2 * INTERVAL + 2))" ] || mark_invalid sampling_gap
    fi
    previous_sample=$sample_now
    # Read threads before dumpsys/thermal scans, but do not rely on this ordering for correctness.
    sample_threads
    usb=$(read_value /sys/class/power_supply/usb/online)
    capacity=$(read_value /sys/class/power_supply/battery/capacity)
    current=$(read_value /sys/class/power_supply/battery/current_now)
    voltage=$(read_value /sys/class/power_supply/battery/voltage_now)
    charge=$(read_value /sys/class/power_supply/battery/charge_counter)
    battery_dump=$(dumpsys -t 3 battery 2>&1)
    printf '=== mono_s=%s epoch_s=%s ===\n%s\n' "$sample_now" "$epoch" "$battery_dump" >> "$OUT/battery-dumps.txt"
    battery_temp=$(printf '%s\n' "$battery_dump" | awk '$1 == "temperature:" { print $2; exit }')
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$sample_now" "$epoch" "$usb" "$capacity" "$current" "$voltage" "$charge" "$battery_temp" >> "$OUT/battery.tsv"
    if [ "$usb" != "$EXPECTED_USB" ]; then
        mark_invalid usb_condition_mismatch_or_unreadable
        abort_app usb_condition_mismatch_or_unreadable
    fi
    if printf '%s\n' "$battery_dump" | awk '/UPDATES STOPPED|mUpdatesStopped=true/ { bad=1 } END { exit !bad }'; then
        mark_invalid simulated_battery_state
        abort_app simulated_battery_state
    fi
    if [ "$EXPECTED_USB" -eq 0 ] && printf '%s\n' "$battery_dump" | awk '/(AC|USB|Wireless) powered: true/ { bad=1 } END { exit !bad }'; then
        mark_invalid external_power_present
        abort_app external_power_present
    fi
    if ! uint "$battery_temp" || [ "$battery_temp" -le 0 ] || [ "$battery_temp" -gt 800 ]; then
        mark_invalid invalid_battery_dumpsys_temperature
    fi
    seen_front=0; seen_back=0; seen_frame=0; seen_battery=0
    for zone in /sys/class/thermal/thermal_zone*; do
        [ -d "$zone" ] || continue
        zone_type=$(read_value "$zone/type" | tr '[:upper:]' '[:lower:]' | tr -c 'A-Za-z0-9_.-' '_')
        raw_temp=$(read_value "$zone/temp")
        valid=0; reason=unreadable_or_noninteger
        if sint "$raw_temp"; then
            reason=out_of_range
            if [ "$raw_temp" -gt 0 ] && [ "$raw_temp" -lt 125000 ]; then valid=1; reason=ok; fi
        fi
        printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$sample_now" "$epoch" "$zone_type" "$raw_temp" "$valid" "$reason" >> "$OUT/thermal.tsv"
        required=0
        case "$zone_type" in
            shell_front) seen_front=1; required=1;;
            shell_back) seen_back=1; required=1;;
            shell_frame) seen_frame=1; required=1;;
            battery|mtktsbattery) seen_battery=1; required=1;;
        esac
        if [ "$required" -eq 1 ] && [ "$valid" -ne 1 ]; then mark_invalid "temperature_${zone_type}_${reason}"; fi
        case "$zone_type" in shell_front|shell_back|shell_frame)
            if [ "$valid" -eq 1 ] && [ "$raw_temp" -ge "$SHELL_GUARD_M" ]; then
                mark_invalid "temperature_guard_${zone_type}"
                abort_app "temperature_guard_${zone_type}"
            fi;;
        esac
    done
    [ "$seen_front" -eq 1 ] || mark_invalid missing_shell_front
    [ "$seen_back" -eq 1 ] || mark_invalid missing_shell_back
    [ "$seen_frame" -eq 1 ] || mark_invalid missing_shell_frame
    [ "$seen_battery" -eq 1 ] || mark_invalid missing_battery_zone
    freq_readable=0
    for policy in /sys/devices/system/cpu/cpufreq/policy*; do
        [ -d "$policy" ] || continue
        frequency=$(read_value "$policy/scaling_cur_freq")
        uint "$frequency" && freq_readable=1
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$sample_now" "${policy##*/}" "$frequency" \
            "$(read_value "$policy/scaling_min_freq")" "$(read_value "$policy/scaling_max_freq")" \
            "$(read_value "$policy/cpuinfo_max_freq")" "$(read_value "$policy/scaling_governor")" \
            "$(read_value "$policy/affected_cpus")" >> "$OUT/cpufreq.tsv"
    done
    [ "$freq_readable" -eq 1 ] || mark_invalid cpufreq_unavailable
    # Keep raw HAL reports; do not substitute cached SKIN_T for invalid surface sensors.
    if [ "$((sample_now - last_thermal_dump))" -ge 60 ]; then
        { printf '=== mono_s=%s epoch_s=%s ===\n' "$sample_now" "$epoch"; dumpsys -t 3 thermalservice; } >> "$OUT/thermalservice.txt" 2>&1
        last_thermal_dump=$sample_now
    fi
    samples=$((samples + 1))
    after_sample=$(mono_s)
    [ "$((after_sample - sample_now))" -le "$INTERVAL" ] || mark_invalid sampling_overrun
    completed_during_sample=0
    if read_completion; then
        completed_during_sample=1
        status COMPLETION_DURING_SAMPLE "sample_start_s=$sample_now sample_end_s=$after_sample result_ms=$completion_ms cpu_unavailable_ms=$cpu_unavailable_ms"
    fi
    if [ "$cpu_unavailable_ms" -ge 0 ]; then
        if [ "$completed_during_sample" -eq 1 ] && [ "$cpu_process_exited" -eq 1 ] &&
            [ "$completion_ms" -le "$((cpu_unavailable_ms + 9))" ] && cpu_coverage_ok; then
            status APP_EXIT_AFTER_COMPLETION "result_ms=$completion_ms last_cpu_ms=$last_cpu_ms cpu_tail_ms=$cpu_tail_ms"
        else
            [ "$cpu_pid_missing" -eq 0 ] || mark_invalid app_pid_missing_or_ambiguous
            mark_invalid app_thread_cpu_or_cpuset_unavailable
        fi
    fi
}

while :; do
    now=$(mono_s)
    app_result=$(read_value "$APP_REPORT/DONE")
    case "$app_result" in
        PASS_PROCESSING_ONLY)
            [ "$samples" -ge 2 ] || finish INSUFFICIENT_SAMPLES 2
            [ "$((now - previous_sample))" -le "$((INTERVAL + 2))" ] || mark_invalid late_last_sample
            if read_completion; then
                cpu_coverage_ok || mark_invalid insufficient_cpu_coverage
                status CPU_COVERAGE "samples=$cpu_samples first_ms=$first_cpu_ms last_ms=$last_cpu_ms result_ms=$completion_ms tail_ms=$cpu_tail_ms limit_ms=$(((INTERVAL + 2) * 1000))"
            else
                mark_invalid invalid_app_completion_report
            fi
            [ "$invalid" -eq 0 ] || finish INVALID_SENSOR_COLLECTION 2
            finish PASS_SENSOR_COLLECTION_ONLY 0;;
        FAIL) finish APP_QUALIFICATION_FAILED 3;;
        '') ;;
        *) finish UNKNOWN_APP_RESULT 3;;
    esac
    if [ "$((now - start_s))" -ge "$MAX_SECONDS" ]; then
        mark_invalid collection_deadline
        abort_app collection_deadline
        finish INCOMPLETE 2
    fi
    if [ "$now" -ge "$next_sample" ]; then
        sample
        next_sample=$((next_sample + INTERVAL))
        after_sample=$(mono_s)
        [ "$after_sample" -lt "$next_sample" ] || next_sample=$((after_sample + INTERVAL))
    fi
    sleep 1
done
