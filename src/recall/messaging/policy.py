from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def quiet(now, settings):
    local = now.astimezone(ZoneInfo(settings["timezone"]))
    clock = local.strftime("%H:%M")
    start, end = settings["quiet_start"], settings["quiet_end"]
    return (
        start <= clock < end
        if start < end
        else clock >= start or clock < end
        if start != end
        else False
    )


def resolve_slot(day, slot, zone):
    """Use the first fold once; move a nonexistent spring time to the next valid minute."""
    naive = datetime.fromisoformat(f"{day.isoformat()}T{slot}")
    for _ in range(181):
        local = naive.replace(tzinfo=zone, fold=0)
        if local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) == naive:
            return local.astimezone(timezone.utc)
        naive += timedelta(minutes=1)
    raise ValueError("No valid time near delivery slot")


def eligible_slot(now, settings):
    if settings["paused"] or not settings["opted_in"] or quiet(now, settings):
        return None
    zone = ZoneInfo(settings["timezone"])
    day = now.astimezone(zone).date()
    candidates = []
    for slot in settings["slots"]:
        instant = resolve_slot(day, slot, zone)
        if timedelta(0) <= now - instant <= timedelta(minutes=30):
            candidates.append((instant, f"{day}:{slot}:{settings['policy_generation']}"))
    return max(candidates)[1] if candidates else None


def next_opportunity(now, settings):
    if settings["paused"] or not settings["opted_in"]:
        return None
    zone = ZoneInfo(settings["timezone"])
    day = now.astimezone(zone).date()
    options = []
    for offset in range(8):
        for slot in settings["slots"]:
            instant = resolve_slot(day + timedelta(days=offset), slot, zone)
            if instant > now and not quiet(instant, settings):
                options.append(instant)
    return min(options).isoformat() if options else None
