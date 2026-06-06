"""
UK Daily Tides Email Bot
Data source : Environment Agency Tide Gauge API (FREE, no key required)
Email       : Gmail SMTP (free, uses App Password)
"""

import os
import smtplib
import requests
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from PIL import Image, ImageDraw, ImageFont

# ─── BST HELPER ──────────────────────────────────────────────────────────────

def to_local_time(utc_dt):
    """Converts UTC datetime to UK local time (BST in summer, GMT in winter)."""
    import time
    # UK is UTC+1 during BST (last Sunday March to last Sunday October)
    year = utc_dt.year
    # Find last Sunday in March
    import calendar
    def last_sunday(year, month):
        last_day = calendar.monthrange(year, month)[1]
        for day in range(last_day, 0, -1):
            if datetime(year, month, day).weekday() == 6:
                return datetime(year, month, day, 1, 0, tzinfo=timezone.utc)
    bst_start = last_sunday(year, 3)
    bst_end   = last_sunday(year, 10)
    if bst_start <= utc_dt.replace(tzinfo=timezone.utc) < bst_end:
        from datetime import timedelta
        return utc_dt + timedelta(hours=1), "BST"
    return utc_dt, "GMT"

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

GMAIL_USER     = "stevencocks77@gmail.com"
GMAIL_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
EMAIL_TO       = "stevencocks77@gmail.com"
EA_BASE        = "https://environment.data.gov.uk/flood-monitoring"
PIXABAY_KEY    = os.environ.get("PIXABAY_API_KEY", "")

# Search terms rotated daily for variety
PHOTO_SEARCHES = [
    "Cornwall coast beach", "Devon coastline sea", "St Ives Cornwall",
    "Newquay beach surf", "Plymouth Sound", "Cornish harbour",
    "Devon beach sunset", "Cornwall cliffs ocean", "Penzance Cornwall",
    "Ilfracombe Devon coast"
]

# Target station names to search for — the script finds the correct IDs automatically
TARGET_STATIONS = [
    "Plymouth", "Newlyn", "Ilfracombe",
    "Bournemouth", "Weymouth", "Hinkley",
]

# Friendlier display names shown on the image
DISPLAY_NAMES = {
    "Plymouth":   "Plymouth / Looe",
    "Newlyn":     "Newlyn / Penzance / St Ives",
    "Ilfracombe": "Ilfracombe / N Devon",
    "Bournemouth":"Bournemouth / Poole",
    "Weymouth":   "Weymouth / Dorset",
    "Portsmouth": "Portsmouth / Solent",
    "Avonmouth":  "Avonmouth / Bristol",
    "Barmouth":   "Barmouth / W Wales",
    "Hinkley":    "Hinkley Pt / Somerset",
    "Lyme Regis": "Lyme Regis / Jurassic Coast",
}

# ─── STATION DISCOVERY ───────────────────────────────────────────────────────

def find_stations():
    """Fetches all tide gauge stations and matches by name."""
    print("  Looking up station IDs...")
    try:
        r = requests.get(f"{EA_BASE}/id/stations?type=TideGauge&_limit=100", timeout=15)
        all_stations = r.json().get("items", [])
    except Exception as e:
        print(f"  Could not fetch station list: {e}")
        return {}

    found = {}
    for target in TARGET_STATIONS:
        for s in all_stations:
            label = s.get("label", "")
            if target.lower() in label.lower():
                station_id = s.get("stationReference") or s.get("@id","").split("/")[-1]
                found[station_id] = {"name": target, "label": label}
                print(f"  Found: {target} → {station_id} ({label})")
                break
        else:
            print(f"  Not found: {target}")

    return found

# ─── DATA FETCHING ────────────────────────────────────────────────────────────

def get_tide_readings(station_id):
    result = {"latest_level": None, "trend": "—", "today_readings": [], "highs": [], "lows": [], "error": False}
    try:
        # Use last 24 hours instead of just today so we always have data
        url = f"{EA_BASE}/id/stations/{station_id}/readings?_sorted&_limit=200"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            print(f"    HTTP {r.status_code} for {station_id}")
            result["error"] = True
            return result

        items = r.json().get("items", [])
        if not items:
            print(f"    Empty response from API for {station_id} - items count: {len(items)}")
            result["error"] = True
            return result

        readings = []
        for item in items:
            try:
                val = float(item["value"])
                ts  = datetime.fromisoformat(item["dateTime"].replace("Z", "+00:00"))
                readings.append((ts, val))
            except (KeyError, ValueError):
                continue

        if not readings:
            result["error"] = True
            return result

        result["today_readings"] = readings
        latest_ts, latest_val    = readings[-1]
        result["latest_level"]   = round(latest_val, 2)
        local_ts, tz_label = to_local_time(latest_ts)
        result["latest_time"]    = local_ts.strftime("%H:%M") + f" {tz_label}"

        if len(readings) >= 3:
            recent, earlier = readings[-1][1], readings[-3][1]
            if   recent > earlier + 0.05: result["trend"] = "Rising"
            elif recent < earlier - 0.05: result["trend"] = "Falling"
            else:                          result["trend"] = "Slack"

        result["highs"], result["lows"] = detect_peaks(readings)

    except Exception as e:
        print(f"    Error: {e}")
        result["error"] = True

    return result


def detect_peaks(readings):
    highs, lows, values = [], [], [v for _, v in readings]
    times  = [t for t, _ in readings]
    window = 4
    for i in range(window, len(values) - window):
        seg = values[i - window: i + window + 1]
        if values[i] == max(seg) and values[i] > values[i-1]: highs.append((times[i], values[i]))
        if values[i] == min(seg) and values[i] < values[i-1]: lows.append((times[i],  values[i]))
    return highs, lows

# ─── PHOTO FETCH ─────────────────────────────────────────────────────────────

def fetch_coastal_photo():
    """Fetches a free coastal photo from Pixabay, rotated daily."""
    if not PIXABAY_KEY:
        print("  No Pixabay key — skipping photo")
        return None
    try:
        import random
        search = PHOTO_SEARCHES[datetime.now().timetuple().tm_yday % len(PHOTO_SEARCHES)]
        print(f"  Fetching photo: {search}")
        params = {
            "key": PIXABAY_KEY,
            "q": search,
            "image_type": "photo",
            "orientation": "horizontal",
            "category": "nature",
            "min_width": 1200,
            "safesearch": "true",
            "per_page": 10
        }
        r = requests.get("https://pixabay.com/api/", params=params, timeout=15)
        print(f"  Pixabay status: {r.status_code}")
        if r.status_code != 200:
            print(f"  Pixabay error: {r.text[:200]}")
            return None
        hits = r.json().get("hits", [])
        if not hits:
            print("  No photos found")
            return None
        # Pick a different photo each day
        photo = hits[datetime.now().day % len(hits)]
        img_url = photo["webformatURL"]
        img_r = requests.get(img_url, timeout=15)
        from io import BytesIO
        img = Image.open(BytesIO(img_r.content)).convert("RGB")
        print(f"  Photo fetched: {photo.get('pageURL','')}")
        return img, photo.get("user", "Pixabay")
    except Exception as e:
        print(f"  Photo fetch failed: {e}")
        return None

# ─── IMAGE GENERATION ────────────────────────────────────────────────────────

BG      = (10, 15, 25)
SURFACE = (20, 30, 48)
BORDER  = (0, 180, 140)
HI_COL  = (0, 200, 160)
LO_COL  = (255, 120, 60)
TEXT    = (220, 235, 255)
MUTED   = (120, 145, 175)
TITLE   = (0, 210, 160)


def font(size, bold=False):
    paths = [
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/liberation/LiberationSans-{'Bold' if bold else 'Regular'}.ttf",
    ]
    for p in paths:
        try: return ImageFont.truetype(p, size)
        except: pass
    return ImageFont.load_default()


def sparkline(draw, readings, x, y, w, h):
    if len(readings) < 4: return
    vals = [v for _, v in readings]
    mn, mx = min(vals), max(vals)
    rng = mx - mn or 1
    pts = [(x + int(i/(len(readings)-1)*w),
            y + h - int(((v-mn)/rng)*h))
           for i, (_, v) in enumerate(readings)]
    for i in range(len(pts)-1):
        draw.line([pts[i], pts[i+1]], fill=HI_COL, width=2)


def generate_image(tide_data, photo_data=None):
    img  = Image.new("RGB", (1080, 1080), BG)
    draw = ImageDraw.Draw(img)

    # Grid
    for y in range(0, 1080, 60): draw.line([(0,y),(1080,y)], fill=(20,28,42))

    # Header
    draw.rectangle([(0,0),(1080,110)], fill=(15,22,38))
    draw.line([(0,110),(1080,110)], fill=BORDER, width=2)
    draw.text((40,22),  "UK TIDE TIMES",                              font=font(46,True), fill=TITLE)
    draw.text((40,78),  datetime.now().strftime("%A %d %B %Y"),       font=font(22),      fill=MUTED)
    draw.text((1070,1070), "Data: Environment Agency (OGL)",          font=font(11),      fill=(50,70,90), anchor="rb")

    # Cards
    cw, ch = 480, 170
    mx, my, gx, gy = 35, 125, 30, 18

    for idx, (sid, info) in enumerate(tide_data.items()):
        col, row = idx % 2, idx // 2
        cx = mx + col*(cw+gx)
        cy = my + row*(ch+gy)
        d  = info["data"]

        draw.rectangle([(cx,cy),(cx+cw,cy+ch)],     fill=SURFACE)
        draw.rectangle([(cx,cy),(cx+cw,cy+ch)],     outline=(35,55,80))
        draw.rectangle([(cx,cy),(cx+4, cy+ch)],     fill=BORDER)
        draw.text((cx+16, cy+12), info["name"].upper(), font=font(19,True), fill=TEXT)

        if d["error"]:
            draw.text((cx+16, cy+45), "No data yet today", font=font(15), fill=MUTED)
            continue

        tc = HI_COL if "Rising" in d["trend"] else LO_COL if "Falling" in d["trend"] else MUTED
        draw.text((cx+cw-10, cy+14), d["trend"], font=font(13), fill=tc, anchor="ra")
        draw.text((cx+16, cy+40),   f"Now: {d['latest_level']}m  ({d['latest_time']} UTC)", font=font(15), fill=MUTED)

        yo = 65
        draw.text((cx+16, cy+yo), "HIGH TIDES", font=font(12), fill=HI_COL); yo+=16
        if d["highs"]:
            for ts,v in d["highs"][:2]:
                local_ts_h, tz_h = to_local_time(ts)
                draw.text((cx+16, cy+yo), f"  {local_ts_h.strftime('%H:%M')} {tz_h}  {v:.2f}m", font=font(15), fill=HI_COL); yo+=18
        else:
            draw.text((cx+16, cy+yo), "  Not yet today", font=font(14), fill=MUTED); yo+=18

        draw.text((cx+16, cy+yo), "LOW TIDES",  font=font(12), fill=LO_COL); yo+=16
        if d["lows"]:
            for ts,v in d["lows"][:2]:
                draw.text((cx+16, cy+yo), f"  {ts.strftime('%H:%M')}  {v:.2f}m", font=font(15), fill=LO_COL); yo+=18
        else:
            draw.text((cx+16, cy+yo), "  Not yet today", font=font(14), fill=MUTED)

        if d["today_readings"]:
            sparkline(draw, d["today_readings"], cx+cw-158, cy+38, 148, 112)

    # Footer
    draw.rectangle([(0,1032),(1080,1080)], fill=(15,22,38))
    draw.line([(0,1032),(1080,1032)], fill=(35,55,80))
    draw.text((40,1046), "Plan your coastal day safely  #UKTides #CoastalSafety #UKCoast", font=font(13), fill=MUTED)

    path = "uk_tides_today.jpg"
    img.save(path, "JPEG", quality=95)
    print(f"Image saved: {path}")
    return path

# ─── PHOTO POST GENERATION ──────────────────────────────────────────────────

def generate_photo_post(photo_data):
    """Generates a full 1080x1080 coastal photo post for Instagram."""
    if not photo_data:
        print("  No photo data — skipping photo post")
        return None
    try:
        photo_img, photographer = photo_data
        # Resize to fill 1080x1080
        ratio = max(1080 / photo_img.width, 1080 / photo_img.height)
        new_w = int(photo_img.width * ratio)
        new_h = int(photo_img.height * ratio)
        photo_img = photo_img.resize((new_w, new_h), Image.LANCZOS)
        # Crop to centre square
        left = (new_w - 1080) // 2
        top  = (new_h - 1080) // 2
        photo_img = photo_img.crop((left, top, left + 1080, top + 1080))

        draw = ImageDraw.Draw(photo_img)

        # Dark gradient overlay at bottom
        from PIL import ImageFilter
        for i in range(400):
            opacity = int((i / 400) * 180)
            draw.line([(0, 1080 - i), (1080, 1080 - i)], fill=(0, 0, 0, opacity))

        # Title
        draw.text((50, 820), "🌊 UK COASTAL GUIDE", font=font(38, True), fill=(0, 210, 160))
        draw.text((50, 875), datetime.now().strftime("%A %d %B %Y"), font=font(26), fill=(220, 235, 255))
        draw.text((50, 920), "Plan your coastal visit around the tides", font=font(20), fill=(180, 200, 220))
        draw.text((50, 960), "#Cornwall #Devon #UKCoast #CoastalLife #BeachLife", font=font(17), fill=(120, 145, 175))
        draw.text((50, 990), "#Surfing #Sailing #UKBeach #CoastalWalking #Newquay", font=font(17), fill=(120, 145, 175))
        draw.text((1030, 1060), f"Photo: {photographer} / Pixabay", font=font(12), fill=(100, 120, 140), anchor="rb")

        path = "uk_coast_photo.jpg"
        photo_img.save(path, "JPEG", quality=95)
        print(f"  Photo post saved: {path}")
        return path
    except Exception as e:
        print(f"  Photo post failed: {e}")
        return None

# ─── EMAIL ────────────────────────────────────────────────────────────────────

def send_email(image_path, photo_path=None):
    if not GMAIL_PASSWORD:
        print("No Gmail app password — skipping email.")
        return

    today = datetime.now().strftime("%d %B %Y")
    msg   = MIMEMultipart()
    msg["From"]    = GMAIL_USER
    msg["To"]      = EMAIL_TO
    msg["Subject"] = f"UK Tide Times — {today}"

    body = (
        f"Your daily UK tide image is attached for {today}.\n\n"
        "Save it and post to Instagram with this caption:\n\n"
        f"🌊 UK High & Low Tide Times — {datetime.now().strftime('%d/%m/%Y')}\n"
        "Covering 10 coastal stations around the UK.\n"
        "Data from the Environment Agency, updated every 15 minutes.\n"
        "Stay safe on the coast! 🏄\n"
        "#UKTides #CoastalSafety #UKCoast #BeachLife #TideTimes "
        "#Sailing #Surfing #UKBeach #CoastalWalking #Fishing"
    )
    msg.attach(MIMEText(body, "plain"))

    with open(image_path, "rb") as f:
        att = MIMEImage(f.read(), name="uk_tides_today.jpg")
    msg.attach(att)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_PASSWORD)
            s.sendmail(GMAIL_USER, EMAIL_TO, msg.as_string())
        print(f"Email sent to {EMAIL_TO}")
    except Exception as e:
        print(f"Email failed: {e}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print(f"UK Tides Bot — {datetime.now().strftime('%d %b %Y %H:%M')}")
    print("-" * 50)

    print("Finding stations...")
    stations = find_stations()
    if not stations:
        print("No stations found — aborting.")
        return

    print(f"\nFetching readings for {len(stations)} stations...")
    tide_data = {}
    for sid, info in stations.items():
        print(f"  {info['name']}...")
        display = DISPLAY_NAMES.get(info["name"], info["name"])
        tide_data[sid] = {**info, "name": display, "data": get_tide_readings(sid)}

    print("\nFetching coastal photo...")
    photo_data = fetch_coastal_photo()
    print("\nGenerating tide image...")
    image_path = generate_image(tide_data)
    print("\nGenerating photo post...")
    photo_path = generate_photo_post(photo_data)
    print("\nSending email...")
    send_email(image_path, photo_path)

    print("\nDone.")

if __name__ == "__main__":
    main()
