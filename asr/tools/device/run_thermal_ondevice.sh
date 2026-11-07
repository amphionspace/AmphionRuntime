#!/system/bin/sh
OUT=/sdcard/amphion_thermal
PKG=com.amphion.dingqiao.demo
INTERVAL=${INTERVAL:-60}
MODE=${MODE:-full}
STAB_MAX=${STAB_MAX:-3600}
LOCK_AFTER=${LOCK_AFTER:-600}
TOTAL_S=${TOTAL_S:-3720}
mkdir -p $OUT
cmd deviceidle whitelist +$PKG >/dev/null 2>&1
LOG=$OUT/samples.csv
TOP=$OUT/top.txt
echo "epoch,elapsed_s,phase,shell_frame_m,shell_front_m,shell_back_m,battery_m,usb_online,level,demo_pid" > $LOG
: > $TOP
T0=$(date +%s)
echo "start epoch=$T0 mode=$MODE interval=$INTERVAL" > $OUT/status.txt

t() { cat /sys/class/thermal/thermal_zone$1/temp 2>/dev/null; }

sample() {
  now=$(date +%s)
  pid=$(pidof $PKG)
  echo "$now,$((now-T0)),$1,$(t 25),$(t 26),$(t 27),$(t 24),$(cat /sys/class/power_supply/usb/online 2>/dev/null),$(cat /sys/class/power_supply/battery/capacity 2>/dev/null),$pid" >> $LOG
  if [ -n "$pid" ]; then
    echo "== $now phase=$1" >> $TOP
    top -H -b -n 1 -p $pid | head -30 >> $TOP
  fi
}

wait_s() {
  end=$(( $(date +%s) + $1 ))
  while [ $(date +%s) -lt $end ]; do sleep 1; done
}

if [ "$MODE" = "dry" ]; then
  i=0
  while [ $i -lt 12 ]; do sample dry; wait_s $INTERVAL; i=$((i+1)); done
  echo DONE > $OUT/DONE; exit 0
fi

if [ "$MODE" = "validate" ]; then
  echo "validate_mode: skipping baseline stability wait (charging allowed)" >> $OUT/status.txt
  sample baseline
else
  echo "baseline_wait" >> $OUT/status.txt
  stable=0; prev=""; bstart=$(date +%s)
  while true; do
    cur=$(t 26)
    sample baseline
    if [ "$(cat /sys/class/power_supply/usb/online 2>/dev/null)" != "0" ]; then stable=0; fi
    if [ -n "$prev" ] && [ -n "$cur" ]; then
      d=$((cur-prev)); [ $d -lt 0 ] && d=$((0-d))
      if [ $d -le 300 ]; then stable=$((stable+1)); else stable=0; fi
    fi
    prev=$cur
    [ $stable -ge 5 ] && break
    [ $(( $(date +%s) - bstart )) -ge $STAB_MAX ] && { echo "stab_timeout" >> $OUT/status.txt; break; }
    wait_s $INTERVAL
  done
fi
echo "start_temp_shell_front_m=$(t 26) start_temp_shell_back_m=$(t 27) start_epoch=$(date +%s)" >> $OUT/status.txt

settings put system screen_off_timeout 1800000
am force-stop $PKG
am start -n $PKG/.MainActivity --ez demoFileInput true >/dev/null 2>&1
wait_s 25
input swipe 120 280 120 120 300; sleep 1
input swipe 120 300 120 60 300; sleep 1
input swipe 120 300 120 60 300; sleep 1
input swipe 120 300 120 60 300; sleep 1
input tap 120 287
T1=$(date +%s)
echo "talk_tapped epoch=$T1" >> $OUT/status.txt
logcat -v time | grep -iE "dingqiao|amphion" > $OUT/logcat.txt &

locked=0
hot=0
while true; do
  now=$(date +%s); el=$((now-T1))
  if [ $el -ge $TOTAL_S ]; then break; fi
  if [ $el -ge $LOCK_AFTER ] && [ $locked -eq 0 ]; then
    input keyevent 26
    locked=1
    echo "locked epoch=$now" >> $OUT/status.txt
  fi
  if [ $locked -eq 1 ]; then ph=locked; else ph=awake; fi
  sample $ph
  fs=$(t 26)
  if [ -n "$fs" ] && [ $fs -ge 50000 ]; then hot=$((hot+1)); else hot=0; fi
  if [ $hot -ge 3 ]; then
    echo "guard_stop shell_front_m=$fs epoch=$(date +%s)" >> $OUT/status.txt
    am force-stop $PKG
    break
  fi
  wait_s $INTERVAL
done
echo "end epoch=$(date +%s)" >> $OUT/status.txt
echo DONE > $OUT/DONE
