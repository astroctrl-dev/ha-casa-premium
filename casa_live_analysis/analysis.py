"""Read-only CASA traffic quality analysis. Times are HA observations, not RS-485 wire times."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import median

DEFAULT_BASELINE = {"tcp_median_ms": 150.0, "sensor_intervals_ms": {}, "reconnect_min_spacing_s": 250.0, "reconnect_max_gap_s": 6.0}
MIN_CRC_TELEGRAMS = 1000

def _seconds(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, AttributeError):
        return None

def _intervals(events):
    times = sorted(t for e in events if (t := _seconds(e.get("utc"))) is not None)
    return [b-a for a,b in zip(times,times[1:]) if b>=a]

def analyze(events, threshold_seconds=0.5, baseline=None, connected=None, lost=0):
    baseline = baseline or DEFAULT_BASELINE
    counts = Counter(e.get("kind", "unknown") for e in events)
    receives = [e for e in events if e.get("kind") == "tcp_receive"]
    intervals = _intervals(receives)
    gaps = [{"utc": e.get("utc"), "seconds": round(delta,3)}
            for e,delta in zip(sorted(receives,key=lambda e:_seconds(e.get("utc")) or 0)[1:],intervals)
            if delta>threshold_seconds]
    crc = sum(max(0,int(e.get("count",1))) for e in events if e.get("kind")=="crc_error")
    valid = counts["telegram"]
    total = valid+crc
    crc_percent = round(100*crc/total,3) if total else None
    crc_status = ("unknown" if total<MIN_CRC_TELEGRAMS else
                  "ok" if crc_percent<0.1 else "warning" if crc_percent<=1 else "error")
    tcp_median = median(intervals)*1000 if intervals else None
    reference = max(1.0,float(baseline.get("tcp_median_ms",150)))
    # Only a known connection transition can establish a reconnect; long gaps alone cannot.
    unexpected = [g for g in gaps if g["seconds"]>max(0.5,5*reference/1000)]
    tcp_status = ("error" if connected is False else "unknown" if len(intervals)<30 or lost else
                  "error" if any(g["seconds"]>6 for g in unexpected) else
                  "warning" if unexpected else "ok")
    sensor_times = defaultdict(list)
    for e in events:
        if e.get("kind")=="sensor_observation":
            t=_seconds(e.get("utc"))
            if t is not None:
                for key in e.get("keys",[]):
                    sensor_times[str(key)].append(t)
    now = datetime.now(timezone.utc).timestamp()
    sensor_details = {}
    factors = []
    for key,times in sensor_times.items():
        times.sort()
        observed = _intervals([{"utc":datetime.fromtimestamp(t,timezone.utc).isoformat()} for t in times])
        reference_ms = baseline.get("sensor_intervals_ms",{}).get(key)
        if reference_ms is None and len(observed)>=3:
            reference_ms=median(observed)*1000
        if reference_ms and reference_ms>0:
            age=max(0,now-times[-1])
            factor=age/(reference_ms/1000)
            factors.append(factor)
            sensor_details[key]={"factor":round(factor,2),"age_s":round(age,2),"reference_ms":round(reference_ms,1)}
    worst=max(factors) if factors else None
    sensor_status=("unknown" if not factors or lost else "ok" if worst<3 else "warning" if worst<=5 else "error")
    times=[t for e in events if (t:=_seconds(e.get("utc"))) is not None]
    return {
        "events":len(events),"duration_seconds":round(max(times)-min(times),3) if len(times)>1 else None,
        "counts":dict(counts),"tcp_bytes":sum(int(e.get("bytes",0)) for e in receives),
        "tcp_interval_median_ms":round(tcp_median,1) if tcp_median is not None else None,
        "tcp_interval_max_ms":round(max(intervals)*1000,1) if intervals else None,
        "gaps_over_threshold":len(gaps),"largest_gaps":sorted(gaps,key=lambda g:-g["seconds"])[:20],
        "crc_errors":crc,"crc_checked":total,"crc_error_percent":crc_percent,
        "telegram_commands":dict(Counter(e.get("command") for e in events if e.get("kind")=="telegram" and e.get("command"))),
        "sensor_keys":dict(Counter(key for e in events if e.get("kind")=="sensor_observation" for key in e.get("keys",[]))),
        "quality":{"tcp":{"status":tcp_status,"unexpected_gaps":len(unexpected)},
                   "crc":{"status":crc_status,"percent":crc_percent,"checked":total},
                   "sensor":{"status":sensor_status,"worst_factor":round(worst,2) if worst is not None else None,"details":sensor_details}},
        "limits":["HA receive timestamps are not physical RS-485 timestamps.",
                  "TCP gaps alone cannot prove a reconnect; they are not automatically exempted.",
                  "Sensor freshness is based on observed update events; absent sensors require configured expectations.",
                  "Quality is unknown when event loss or insufficient sample size prevents reliable assessment."]
    }

def calibrate(events):
    """Build a candidate only; caller must reject poor-quality samples before saving."""
    report=analyze(events)
    if report["duration_seconds"] is None or report["duration_seconds"]<1800:
        raise ValueError("Kalibrering krever minst 30 minutter med data")
    if report["quality"]["crc"]["status"] not in ("ok",):
        raise ValueError("CRC-kvalitet er ikke verifisert som normal")
    if report["quality"]["tcp"]["status"] not in ("ok",):
        raise ValueError("TCP-mottak har avvik eller utilstrekkelige data")
    receive_intervals=_intervals([e for e in events if e.get("kind")=="tcp_receive"])
    baseline=dict(DEFAULT_BASELINE)
    baseline["tcp_median_ms"]=round(median(receive_intervals)*1000,1)
    sensor_times=defaultdict(list)
    for e in events:
        if e.get("kind")=="sensor_observation":
            t=_seconds(e.get("utc"))
            if t is not None:
                for key in e.get("keys",[]): sensor_times[str(key)].append(t)
    baseline["sensor_intervals_ms"]={}
    for key,times in sensor_times.items():
        times.sort()
        intervals=[b-a for a,b in zip(times,times[1:]) if b>=a]
        if len(intervals)>=10:
            baseline["sensor_intervals_ms"][key]=round(median(intervals)*1000,1)
    if not baseline["sensor_intervals_ms"]:
        raise ValueError("For få sensoroppdateringer til å kalibrere")
    return baseline
