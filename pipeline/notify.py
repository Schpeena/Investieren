"""Push notifikace přes ntfy.sh (zdarma, appka ntfy pro iOS). Publikace jako JSON => plná podpora UTF-8 (čeština, šipky)."""
import json
import urllib.request

def push(topic, title, body, link=None, priority=3, tags=None):
    if not topic:
        print(f"[notify-skip] {title}")
        return False
    payload = {"topic": topic, "title": title, "message": body, "priority": priority,
               "tags": tags or ["chart_with_upwards_trend"]}
    if link:
        payload["click"] = link
    req = urllib.request.Request("https://ntfy.sh/", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
        return True
    except Exception as e:
        print(f"[warn] ntfy: {e}")
        return False
