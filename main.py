import discord
from discord.ext import commands, tasks
import aiohttp
import os
import sys
import io, csv, zipfile
import asyncio
from datetime import datetime, timedelta 

# =======================
# BEÁLLÍTÁSOK
# =======================

TOKEN = os.getenv("TOKEN")

API_BASE = "https://bkv-realtime-map.hu/vehicles"

STOP_API = f"{API_BASE}/stop?stopId={{stop_id}}"
VEHICLES_API = f"{API_BASE}/vehicles"

# WATCH_STOPS = {
#     "166","289","346","391","725","792","1008","1112","1247","1333",
#     "1346","1800","1935","1994","2185","2225","2228","2360","2391",
#     "2432","2502","2503","2544","2549","2587","2588","2900","2901",
#     "2902","1989"
# }

TRAM_LINES = {"3010", "3011", "3020", "3022", "3030", "3040", "3060", "3120", "3140", "3170", "3190", "3230", "3240", "3280", "3281", "3370", "3371", "3410", "3420", "3470", "3480", "3490", "3500", "3510", "3511", "3520", "3560", "3561", "3590", "3591", "3592", "3600", "3610", "3620", "3621", "3690", " ", "-", "9999", "9997", "R3180", "R3230", "R3360", "R3800", "R3118", "N3560", "N3020", "N3180", "N3190", "N3600"}

# VONAL MAPPING
LINE_MAP = {
    "3010": "1",
    "3011": "1A",
    "3020": "2",
    "3022": "2B",
    "3030": "3",
    "3040": "4",
    "3060": "6",
    "3120": "12",
    "3140": "14",
    "3170": "17",
    "3190": "19",
    "3230": "23",
    "3240": "24",
    "3280": "28",
    "3281": "28A",
    "3370": "37",
    "3371": "37A",
    "3410": "41",
    "3420": "42",
    "3470": "47",
    "3480": "48",
    "3490": "49",
    "3500": "50",
    "3510": "51",
    "3511": "51A",
    "3520": "52",
    "3560": "56",
    "3561": "56A",
    "3590": "59",
    "3591": "59A",
    "3592": "59B",
    "3600": "60 *Fogaskerekű*",
    "3610": "61",
    "3620": "62",
    "3621": "62A",
    "3690": "69",
    "R3180": "R18",
    "R3230": "R23",
    "R3360": "R36",
    "R3800": "R80",
    "R3118": "R118",
    "N3560": "N56",
    "N3020": "N2",
    "N3180": "N18",
    "N3190": "N19"
}

POTLAS_TIPUSOK = {
    "t5c5",
    "t5c5k2",
    "ics",
    "kcsv7"
    "combino",
    "caf5",
    "caf9",
    "tw6000"
}


LOCK_FILE = "/tmp/discord_bot.lock"

if os.path.exists(LOCK_FILE):
    print("A bot már fut, kilépés.")
    sys.exit(0)

active_today_villamos = {}
active_today_combino = {}
active_today_caf5 = {}
active_today_caf9 = {}
active_today_tatra = {}
today_data = {}

# =======================
# DISCORD INIT
# =======================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=".", intents=intents)

# ─────────────────────────────────────────────
# GTFS SEGÉD
# ─────────────────────────────────────────────

def open_gtfs(name):
    z = zipfile.ZipFile(GTFS_PATH)
    return io.TextIOWrapper(z.open(name), encoding="utf-8-sig")

def tsec(t):
    try:
        h, m, s = map(int, t.split(":"))
        return h*3600 + m*60 + s
    except:
        return 10**9

def daily_forda_id(block_id):
    # csak ha van block_id!
    p = block_id.split("_")
    return f"{p[-3]}_{p[-2]}"

def forgalmi_from_dfid(dfid):
    try:
        return int(dfid.split("_")[-1])
    except:
        return None

def service_active(service_id, date):
    return SERVICE_DATES.get(service_id, {}).get(date, False)

def load_gtfs():
    # trips.txt
    with open_gtfs("trips.txt") as f:
        for r in csv.DictReader(f):
            TRIPS_META[r["trip_id"]] = r

    # stops.txt
    with open_gtfs("stops.txt") as f:
        for r in csv.DictReader(f):
            STOPS[r["stop_id"]] = r["stop_name"]

    # stop_times.txt (első indulás és teljes stop lista)
    first = {}
    with open_gtfs("stop_times.txt") as f:
        for r in csv.DictReader(f):
            tid = r["trip_id"]
            seq = int(r["stop_sequence"])
            if tid not in first or seq < first[tid]:
                first[tid] = seq
                TRIP_START[tid] = r["departure_time"]

            TRIP_STOPS[tid].append({
                "seq": seq,
                "stop_id": r["stop_id"],
                "arrival": r["arrival_time"],
                "departure": r["departure_time"]
            })

    # calendar_dates.txt
    with open_gtfs("calendar_dates.txt") as f:
        for r in csv.DictReader(f):
            date = datetime.strptime(r["date"], "%Y%m%d").date()
            if r["exception_type"] == "1":
                SERVICE_DATES[r["service_id"]][date] = True
            elif r["exception_type"] == "2":
                SERVICE_DATES[r["service_id"]][date] = False

    # fordák
    count_total = 0
    count_with_bid = 0
    for tid, t in TRIPS_META.items():
        count_total += 1
        bid = t.get("block_id")
        if not bid:
            continue
        count_with_bid += 1
        rid = t["route_id"]
        dfid = daily_forda_id(bid)

        # Stop adatok
        stops = sorted(TRIP_STOPS[tid], key=lambda x: x["seq"])
        if stops:
            first_stop = stops[0]
            last_stop = stops[-1]
            first_stop_name = STOPS.get(first_stop["stop_id"], "Ismeretlen")
            last_stop_name = STOPS.get(last_stop["stop_id"], "Ismeretlen")
            first_time = first_stop["departure"]
            last_time = last_stop["arrival"]
        else:
            first_stop_name = last_stop_name = first_time = last_time = ""

        ROUTES[rid][dfid].append({
            "trip_id": tid,
            "start_time": TRIP_START.get(tid, ""),
            "headsign": t["trip_headsign"],
            "service_id": t["service_id"],
            "orig_block_id": bid,
            "first_stop": first_stop_name,
            "last_stop": last_stop_name,
            "first_time": first_time,
            "last_time": last_time
        })

    print(f"Total trips: {count_total}, with block_id: {count_with_bid}")
    print(f"ROUTES keys: {list(ROUTES.keys())[:10]}")  # Első 10

    for rid in ROUTES:
        for dfid in ROUTES[rid]:
            ROUTES[rid][dfid].sort(key=lambda x: tsec(x["start_time"]))

def parse_txt_feed():
    try:
        text = requests.get(TXT_URL, timeout=10).text
    except:
        return {}

    mapping = {}
    cur = {"id": None, "license_plate": None, "vehicle_model": None}

    def commit():
        if cur["id"]:
            mapping[cur["id"]] = {
                "license_plate": cur["license_plate"] or "N/A",
                "vehicle_model": cur["vehicle_model"] or "N/A",
            }

    for l in text.splitlines():
        l = l.strip()
        if l.startswith('id: "'):
            commit()
            cur = {"id": l.split('"')[1], "license_plate": None, "vehicle_model": None}
        elif l.startswith('license_plate: "'):
            cur["license_plate"] = l.split('"')[1]
        elif 'vehicle_model:' in l:
            p = l.split('"')
            if len(p) >= 2:
                cur["vehicle_model"] = p[1]

    commit()
    return mapping

def menetrendi_forgalmi(block_id):
    if not block_id:
        return "?"
    p = block_id.split("_")
    return p[2] if len(p) >= 4 and p[2].isdigit() else "?"

def is_low_floor(trip_id):
    t = TRIPS_META.get(trip_id)
    return t and t.get("wheelchair_accessible") == "1"

def chunk_messages(header, lines):
    msg = header + "\n\n"
    for l in lines:
        if len(msg) + len(l) > DISCORD_LIMIT:
            yield msg.rstrip()
            msg = l + "\n\n"  # Folytatás header nélkül
        else:
            msg += l + "\n\n"
    if msg.strip():
        yield msg.rstrip()

# =======================
# SEGÉDFÜGGVÉNYEK
# =======================

from datetime import datetime, timedelta

def resolve_date(date_str: str | None):
    if not date_str:
        return datetime.now().date()

    date_str = date_str.lower()

    if date_str in {"today", "ma"}:
        return datetime.now().date()

    if date_str in {"yesterday", "tegnap"}:
        return (datetime.now() - timedelta(days=1)).date()

    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def in_bbox(lat, lon):
    return (
        47.35 <= lat <= 47.60 and
        18.90 <= lon <= 19.30
    )

# jármű+forgalmi → utolsó log idő
last_seen = {}
LOG_INTERVAL = 300  # másodperc (5 perc)

def ensure_dirs():
    os.makedirs("logs", exist_ok=True)
    os.makedirs("logs/veh", exist_ok=True)
    
NOSZTALGIA = {"4000", "4171", "4200", "4349", "JARMU1", "JARMU2", "JARMU3"}

def is_nosztalgia(reg):
    if not is_t5c5k2(reg):
        return False
    return reg in NOSZTALGIA  

def is_tw6000(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("V"):
        return False
    if not reg[1:].isdigit():
        return False
    return 1500 <= int(reg[1:]) <= 1624 

def is_fogas(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("F00"):
        return False
    if not reg[1:].isdigit():
        return False
    return 50 <= int(reg[1:]) <= 70 

# T5C5 konkrét pályaszámok
T5C5_NUMBERS = {
    "V4000", "V4014", "V4015", "V4048", "V4054", "V4055",
    "V4154", "V4155", "V4166", "V4171", "V4200", "V4272",
    "V4288", "V4320", "V4322", "V4335", "V4336", "V4349"
}

def is_t5c5(reg):
    if not is_t5c5k2(reg):
        return False
    return reg in T5C5_NUMBERS

def is_t5c5k2(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("V"):
        return False
    if not reg[1:].isdigit():
        return False
    return 4000 <= int(reg[1:]) <= 4349 

def is_ganz_troli(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("T"):
        return False
    if not reg[1:].isdigit():
        return False
    n = int(reg[1:])
    return 601 <= n <= 626

KCSV_NUMBERS = {
    "V1321", "V1325", "V1326", "V1327", "V1328", "V1329", "V1330", "V1331",
    "V1332", "V1335", "V1336", "V1337", "V1339", "V1340", "V1343", "V1344",
    "V1345", "V1346", "V1347", "V1348", "V1350", "V1351", "V1352", "V1353",
    "V1354", "V1355", "V1356", "V1359", "V1362", "V1370"
}

def is_ganz(reg):
    """Visszaadja True-t, ha a regisztráció egy Ganz villamos (ICS vagy KCSV7)"""
    if not isinstance(reg, str):
        return False
    if not reg.startswith("V"):
        return False
    if not reg[1:].isdigit():
        return False
    n = int(reg[1:])
    return 1301 <= n <= 1499

def is_kcsv7(reg):
    """Visszaadja True-t, ha a regisztráció egy KCSV7 villamos"""
    return reg in KCSV_NUMBERS

def is_ics(reg):
    """Visszaadja True-t, ha a regisztráció egy ICS villamos"""
    if not is_ganz(reg):
        return False
    return reg not in KCSV_NUMBERS

def is_caf5(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("V"):
        return False
    if not reg[1:].isdigit():
        return False
    n = int(reg[1:])
    return 2200 <= n <= 2300

def is_caf9(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("V"):
        return False
    if not reg[1:].isdigit():
        return False
    n = int(reg[1:])
    return 2100 <= n <= 2130

def is_combino(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("V"):
        return False
    if not reg[1:].isdigit():
        return False
    n = int(reg[1:])
    return 2000 <= n <= 2041

def is_oktato(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("V"):
        return False
    if not reg[1:].isdigit():
        return False
    n = int(reg[1:])
    return 7600 <= n <= 7699

async def fetch_json(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
            if r.status != 200:
                return None
            return await r.json()
    except:
        return None

def get_last_vehicle_reg(veh):
    if not isinstance(veh, list) or not veh:
        return None
    last = veh[-1]
    if not isinstance(last, dict):
        return None
    return last.get("VehicleRegistrationNumber")

def save_trip(trip_id, line, vehicle, dest):
    ensure_dirs()

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    ts = now.strftime("%Y-%m-%d %H:%M:%S")

    trip_dir = f"logs/{today}"
    os.makedirs(trip_dir, exist_ok=True)

    # =========================
    # JÁRAT NAPLÓ (ELSŐ ÉSZLELÉS)
    # =========================
    trip_file = f"{trip_dir}/{trip_id}.txt"
    if not os.path.exists(trip_file):
        with open(trip_file, "w", encoding="utf-8") as f:
            f.write(
                f"Dátum: {today}\n"
                f"ID: {trip_id}\n"
                f"Vonal: {line}\n"
                f"Cél: {dest}\n"
                f"Jármű: {vehicle}\n"
                f"Első észlelés: {ts}\n"
            )

    # =========================
    # JÁRMŰ NAPLÓ (FRISSÍTÉS)
    # =========================
    veh_file = f"logs/veh/{vehicle}.txt"
    os.makedirs("logs/veh", exist_ok=True)

    key = f"{vehicle}_{trip_id}"

    write_log = False

    # ha még sosem láttuk → írunk
    if key not in last_seen:
        write_log = True

    # ha már láttuk, de eltelt 5 perc → írunk
    else:
        delta = (now - last_seen[key]).total_seconds()
        if delta >= LOG_INTERVAL:
            write_log = True

    # ha forgalmi váltás volt → azonnal írunk
    if os.path.exists(veh_file):
        with open(veh_file, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
            if lines and "ID " in lines[-1]:
                last_trip = lines[-1].split("ID ")[1].split(" ")[0]
                if last_trip != trip_id:
                    write_log = True

    if write_log:
        with open(veh_file, "a", encoding="utf-8") as f:
            f.write(f"{ts} - ID {trip_id} - Vonal {line} - {dest}\n")
        last_seen[key] = now


# =======================
# LOGGER LOOP
# =======================

async def refresh_today_data(self):
    await self.wait_until_ready()
    while not self.is_closed():
        veh_dir = "logs/veh"
        today = datetime.now().date()  # csak a dátum
        data = {}

        for fname in os.listdir(veh_dir):
            if not fname.endswith(".txt"):
                continue
            reg = fname.replace(".txt", "")
            if not is_combino(reg):
                continue

            with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        ts_full = line.split(" - ")[0]  # pl. "2026-01-16 06:15:00"
                        ts_date = datetime.strptime(ts_full, "%Y-%m-%d %H:%M:%S").date()
                        if ts_date != today:
                            continue

                        trip_id = line.split("ID ")[1].split(" ")[0]
                        line_no = line.split("Vonal ")[1].split(" ")[0]
                        line_name = LINE_MAP.get(line_no, line_no)
                        data.setdefault(reg, []).append((ts_full, line_name, trip_id))
                    except Exception as e:
                        continue

        today_data[today.strftime("%Y-%m-%d")] = data
        await asyncio.sleep(180)

        

@tasks.loop(minutes=3)
async def update_active_today():
    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_json(session, VEHICLES_API)
        if not isinstance(vehicles, list):
            return

        # Törlés minden frissítés előtt
        active_today_villamos.clear()
        active_today_combino.clear()
        active_today_caf5.clear()
        active_today_caf9.clear()
        active_today_tatra.clear()

        for v in vehicles:
            reg = v.get("license_plate")
            line_id = str(v.get("route_id", "—"))
            line_name = LINE_MAP.get(line_id, line_id)
            dest = v.get("destination", "Ismeretlen")
            lat = v.get("latitude")
            lon = v.get("longitude")
            trip_id = str(v.get("vehicle_id"))
            model = (v.get("vehicle_model") or "").lower()

            if not reg or lat is None or lon is None:
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            # Villamosok
            if "ganz" in model or is_tw6000(reg) or is_combino(reg) or is_caf5(reg) or is_caf9(reg) or is_t5c5(reg) or is_oktato(reg):
                if is_ganz_troli(reg):
                    continue
                entry = active_today_villamos.setdefault(reg, {"line": line_name, "dest": dest, "first": None, "last": None})
                now = datetime.utcnow()
                if not entry["first"]:
                    entry["first"] = now
                entry["last"] = now

                # Specifikus típusok
                if is_combino(reg):
                    entry_c = active_today_combino.setdefault(reg, {"line": line_name, "dest": dest, "first": None, "last": None})
                    if not entry_c["first"]:
                        entry_c["first"] = now
                    entry_c["last"] = now
                if is_caf5(reg):
                    entry_c = active_today_caf5.setdefault(reg, {"line": line_name, "dest": dest, "first": None, "last": None})
                    if not entry_c["first"]:
                        entry_c["first"] = now
                    entry_c["last"] = now
                if is_caf9(reg):
                    entry_c = active_today_caf9.setdefault(reg, {"line": line_name, "dest": dest, "first": None, "last": None})
                    if not entry_c["first"]:
                        entry_c["first"] = now
                    entry_c["last"] = now
                if is_t5c5(reg):
                    entry_c = active_today_tatra.setdefault(reg, {"line": line_name, "dest": dest, "first": None, "last": None})
                    if not entry_c["first"]:
                        entry_c["first"] = now
                    entry_c["last"] = now

@tasks.loop(seconds=30)
async def logger_loop():
    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_json(session, VEHICLES_API)
        if not isinstance(vehicles, list):
            return

        for v in vehicles:
            try:
                line = str(v.get("route_id"))
                reg = v.get("license_plate")
                lat = v.get("latitude")
                lon = v.get("longitude")
                dest = v.get("destination", "Ismeretlen")

                if not reg or not lat or not lon:
                    continue

                if line not in TRAM_LINES:
                    continue

                if not in_bbox(lat, lon):
                    continue

                # mivel nincs trip_id → vehicle_id lesz az
                dep_id = str(v.get("vehicle_id"))

                save_trip(dep_id, line, reg, dest)

            except Exception:
                continue


# =======================
# PARANCSOK – MIND
# =======================

# ────────────────
# BKV Villamos
# ────────────────
@bot.command()
async def bkvvillamos(ctx):
    active = {}
    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_json(session, VEHICLES_API)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            line_id = str(v.get("route_id", "—"))
            line_name = LINE_MAP.get(line_id, line_id)
            dest = v.get("destination", "Ismeretlen")
            lat = v.get("latitude")
            lon = v.get("longitude")
            trip_id = str(v.get("vehicle_id"))
            model = (v.get("vehicle_model") or "").lower()

            if not reg or lat is None or lon is None:
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue
            if not ("ganz" in model or is_tw6000(reg) or is_combino(reg) or
                    is_caf5(reg) or is_caf9(reg) or is_t5c5(reg) or is_oktato(reg)) or is_fogas(reg):
                continue
            if is_ganz_troli(reg):
                continue

            active[reg] = {"line": line_name, "dest": dest, "trip_id": trip_id, "lat": lat, "lon": lon}

    if not active:
        return await ctx.send("🚫 Nincs aktív villamos.")

    # EMBED DARABOLÁS
    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(title="🚋 Aktív villamosok", color=0xffff00)
    field_count = 0

    for reg, i in sorted(active.items()):
        forgalmi = menetrendi_forgalmi(i["trip_id"])
        value = f"Vonal: {i['line']}\nCél: {i['dest']}\nForgalmi szám: {forgalmi}\nPozíció: {i['lat']:.5f}, {i['lon']:.5f}"

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title="🚋 Aktív villamosok (folytatás)", color=0xffff00)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)

KIEMELT_VONALAK_TW = {
    "24", "28", "28A", "37", "37A", "51", "51A", "52", "62", "62A", "69", "9997", "9999", " ", "", "-"
}

KIEMELT_VONALAK_ICS = {
    "2", "47", "48", "49", "9997", "9999", " ", "", "-"
}

KIEMELT_VONALAK_KCSV7 = {
    "2", "2B", "23", "9997", "9999", " ", "", "-"
}

KIEMELT_VONALAK_COMBINO = {
    "4", "6", "9997", "9999", " ", "", "-"
}

KIEMELT_VONALAK_CAF9 = {
    "1", "9997", "9999", " ", "", "-"
}

KIEMELT_VONALAK_CAF5 = {
    "3", "14", "17", "19", "42", "50", "56", "56A", "61", "69", "9997", "9999", " ", "", "-"
}

KIEMELT_VONALAK_T5C5 = {
    "1", "1A", "9997", "9999", " ", "", "-"
}

KIEMELT_VONALAK_T5C5K2 = {
    "1", "1A", "12", "14", "17", "19", "28", "28A", "37", "37A", "41", "56", "56A", "59", "59A", "59B", "61", "9997", "9999", " ", "", "-"
}

# ────────────────
# Ganz
# ────────────────
@bot.command()
async def bkvkcsv7(ctx):
    active = {}
    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_json(session, VEHICLES_API)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            model = (v.get("vehicle_model") or "").lower()
            lat = v.get("latitude")
            lon = v.get("longitude")
            dest = v.get("destination", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = LINE_MAP.get(line_id, line_id)

            if is_ganz_troli(reg) or is_ics(reg):
                continue
            if not reg or lat is None or lon is None:
                continue
            if "ganz" not in model:
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {"line": line_name, "dest": dest, "lat": lat, "lon": lon}

    if not active:
        return await ctx.send("🚫 Nincs aktív Ganz KCSV7 villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(title="🚋 Aktív Ganz KCSV7 villamosok", color=0xffff00)
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title="🚋 Aktív Ganz KCSV7 villamosok (folytatás)", color=0xffff00)
            field_count = 0

        line = i["line"]
        if line not in KIEMELT_VONALAK_KCSV7:
            line_text = f"🔴 **Vonal: {line}**"
        else:
            line_text = f"Vonal: {line}"

        embed.add_field(
            name=reg,
            value=f"{line_text}\nCél: {i['dest']}\nPozíció: {i['lat']:.5f}, {i['lon']:.5f}",
            inline=False
        )
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)

@bot.command()
async def bkvics(ctx):
    active = {}
    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_json(session, VEHICLES_API)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            model = (v.get("vehicle_model") or "").lower()
            lat = v.get("latitude")
            lon = v.get("longitude")
            dest = v.get("destination", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = LINE_MAP.get(line_id, line_id)

            if is_ganz_troli(reg) or is_kcsv7(reg):
                continue
            if not reg or lat is None or lon is None:
                continue
            if "ganz" not in model:
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {"line": line_name, "dest": dest, "lat": lat, "lon": lon}

    if not active:
        return await ctx.send("🚫 Nincs aktív Ganz ICS villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(title="🚋 Aktív Ganz ICS villamosok", color=0xffff00)
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title="🚋 Aktív Ganz ICS villamosok (folytatás)", color=0xffff00)
            field_count = 0

        line = i["line"]
        if line not in KIEMELT_VONALAK_ICS:
            line_text = f"🔴 **Vonal: {line}**"
        else:
            line_text = f"Vonal: {line}"

        embed.add_field(
            name=reg,
            value=f"{line_text}\nCél: {i['dest']}\nPozíció: {i['lat']:.5f}, {i['lon']:.5f}",
            inline=False
        )
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)

# ────────────────
# TW6000
# ────────────────

FIXLEPCSOS = {
    "1500", "1506", "1510", "1532", "1542", "1551", "1552", "1569", "1570", "1573",
    "1583", "1589", "1600", "1601", "1602", "1604", "1605", "1606",
    "1607", "1613", "1614", "1615", "1619", "1624"
}

def normalize_reg(reg):
    if not reg:
        return None
    return "".join(c for c in str(reg) if c.isdigit())

def is_fixlepcsos(reg):
    szam = normalize_reg(reg)
    return szam in FIXLEPCSOS



def normalize_reg(reg):
    if not reg:
        return None
    return "".join(c for c in str(reg) if c.isdigit())

def is_fixlepcsos(reg):
    szam = normalize_reg(reg)
    return szam in FIXLEPCSOS


@bot.command()
async def bkvtw6000(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_json(session, VEHICLES_API)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg_raw = v.get("license_plate")
            lat = v.get("latitude")
            lon = v.get("longitude")
            dest = v.get("destination", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = LINE_MAP.get(line_id, line_id)

            if not reg_raw or lat is None or lon is None:
                continue
            if not is_tw6000(reg_raw):
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            reg = normalize_reg(reg_raw)
            if not reg:
                continue

            active[reg] = {
                "line": line_name,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív TW6000-es villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(
        title="🚋 Aktív TW6000-es villamosok",
        color=0xffe600
    )
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(
                title="🚋 Aktív TW6000-es villamosok (folytatás)",
                color=0xffe600
            )
            field_count = 0

        line = i["line"]
        if line not in KIEMELT_VONALAK_TW:
            line_text = f"🔴 Vonal: **{line}**"
        else:
            line_text = f"Vonal: {line}"

        embed.add_field(
            name=reg,
            value=(
                f"{line_text}\n"
                f"Cél: {i['dest']}\n"
                f"Fixlépcsős: {'Igen' if is_fixlepcsos(reg) else 'Nem'}\n"
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )
        field_count += 1

    embeds.append(embed)

    for e in embeds:
        await ctx.send(embed=e) 

# ────────────────
# Combino
# ────────────────
@bot.command()
async def bkvcombino(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_json(session, VEHICLES_API)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            lat = v.get("latitude")
            lon = v.get("longitude")
            dest = v.get("destination", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = LINE_MAP.get(line_id, line_id)

            if not reg or lat is None or lon is None:
                continue
            if not is_combino(reg):
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {
                "line": line_name,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Combino villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(
        title="🚋 Aktív Combino villamosok",
        color=0xffff00
    )
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(
                title="🚋 Aktív Combino villamosok (folytatás)",
                color=0xffff00
            )
            field_count = 0

        line = i["line"]
        if line not in KIEMELT_VONALAK_COMBINO:
            line_text = f"🔴 Vonal: **{line}**"
        else:
            line_text = f"Vonal: {line}"

        embed.add_field(
            name=reg,
            value=(
                f"{line_text}\n"
                f"Cél: {i['dest']}\n"
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)

@bot.command()
async def bkvoktato(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_json(session, VEHICLES_API)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            lat = v.get("latitude")
            lon = v.get("longitude")
            dest = v.get("destination", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = LINE_MAP.get(line_id, line_id)

            if not reg or lat is None or lon is None:
                continue
            if not is_oktato(reg):
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {
                "line": line_name,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Oktató villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(
        title="🚋 Aktív Oktató villamosok",
        color=0xffff00
    )
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(
                title="🚋 Aktív Oktató villamosok (folytatás)",
                color=0xff0000
            )
            field_count = 0

        embed.add_field(
            name=reg,
            value=(
                f"{line_text}\n"
                f"Cél: {i['dest']}\n"
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)

# ────────────────
# CAF5
# ────────────────
@bot.command()
async def bkvcaf5(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_json(session, VEHICLES_API)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            lat = v.get("latitude")
            lon = v.get("longitude")
            dest = v.get("destination", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = LINE_MAP.get(line_id, line_id)

            if not reg or lat is None or lon is None:
                continue
            if not is_caf5(reg):
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {
                "line": line_name,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív CAF5 villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(
        title="🚋 Aktív CAF5 villamosok",
        color=0xffff00
    )
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(
                title="🚋 Aktív CAF5 villamosok (folytatás)",
                color=0xffff00
            )
            field_count = 0

        line = i["line"]
        if line not in KIEMELT_VONALAK_CAF5:
            line_text = f"🔴 **Vonal: {line}**"
        else:
            line_text = f"Vonal: {line}"

        embed.add_field(
            name=reg,
            value=(
                f"{line_text}\n"
                f"Cél: {i['dest']}\n"
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)



# ────────────────
# CAF9
# ────────────────
@bot.command()
async def bkvcaf9(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_json(session, VEHICLES_API)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            lat = v.get("latitude")
            lon = v.get("longitude")
            dest = v.get("destination", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = LINE_MAP.get(line_id, line_id)

            if not reg or lat is None or lon is None:
                continue
            if not is_caf9(reg):
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {
                "line": line_name,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív CAF9 villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(
        title="🚋 Aktív CAF9 villamosok",
        color=0xffff00
    )
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(
                title="🚋 Aktív CAF9 villamosok (folytatás)",
                color=0xffff00
            )
            field_count = 0

        line = i["line"]
        if line not in KIEMELT_VONALAK_CAF9:
            line_text = f"🔴 **Vonal: {line}**"
        else:
            line_text = f"Vonal: {line}"

        embed.add_field(
            name=reg,
            value=(
                f"{line_text}\n"
                f"Cél: {i['dest']}\n"
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)


# ────────────────
# Tatra (T5C5)
# ────────────────
@bot.command()
async def bkvt5c5(ctx):
    active = {}
    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_json(session, VEHICLES_API)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            lat = v.get("latitude")
            lon = v.get("longitude")
            dest = v.get("destination", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = LINE_MAP.get(line_id, line_id)

            if not reg or lat is None or lon is None:
                continue

            # 🔴 CSAK T5C5
            if not is_t5c5(reg):
                continue

            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {
                "line": line_name,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív T5C5 villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(
        title="🚋 Aktív T5C5 villamosok",
        color=0xffff00
    )
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(
                title="🚋 Aktív T5C5 villamosok (folytatás)",
                color=0xffff00
            )
            field_count = 0

        line = i["line"]
        if line not in KIEMELT_VONALAK_T5C5:
            line_text = f"🔴 **Vonal: {line}**"
        else:
            line_text = f"Vonal: {line}"

        embed.add_field(
            name=reg,
            value=(
                f"{line_text}\n"
                f"Cél: {i['dest']}\n"
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)

@bot.command()
async def bkvt5c5k2(ctx):
    active = {}
    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_json(session, VEHICLES_API)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            lat = v.get("latitude")
            lon = v.get("longitude")
            dest = v.get("destination", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = LINE_MAP.get(line_id, line_id)

            if not reg or lat is None or lon is None:
                continue

            # 🔴 CSAK T5C5K2 (nem sima T5C5)
            if not is_t5c5k2(reg) or is_t5c5(reg):
                continue

            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {
                "line": line_name,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív T5C5K2 villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(
        title="🚋 Aktív T5C5K2 villamosok",
        color=0xffaa00
    )
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(
                title="🚋 Aktív T5C5K2 villamosok (folytatás)",
                color=0xffaa00
            )
            field_count = 0

        line = i["line"]
        if line not in KIEMELT_VONALAK_T5C5K2:
            line_text = f"🔴 **Vonal: {line}**"
        else:
            line_text = f"Vonal: {line}"

        embed.add_field(
            name=reg,
            value=(
                f"{line_text}\n"
                f"Cél: {i['dest']}\n"
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)
# ────────────────
# Fogaskerekű
# ────────────────
@bot.command()
async def bkvfogas(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_json(session, VEHICLES_API)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            lat = v.get("latitude")
            lon = v.get("longitude")
            dest = v.get("destination", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = LINE_MAP.get(line_id, line_id)

            if not reg or lat is None or lon is None:
                continue
            if not is_fogas(reg):
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {
                "line": line_name,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Fogaskerekű.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(
        title="🚋 Aktív Fogaskerekűek",
        color=0xffff00
    )
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(
                title="🚋 Aktív Fogaskerekűek (folytatás)",
                color=0xffff00
            )
            field_count = 0

        line = i["line"]
        line_text = f"Vonal: {line}"

        embed.add_field(
            name=reg,
            value=(
                f"{line_text}\n"
                f"Cél: {i['dest']}\n"
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)

# @bot.command()
# async def allnosztalgia(ctx):
#     active = {}
#     async with aiohttp.ClientSession() as session:
#         for stop_id in WATCH_STOPS:
#             stop_data = await fetch_json(session, STOP_API.format(stop_id=stop_id))
#             if not isinstance(stop_data, list):
#                 continue

#             for dep in stop_data:
#                 line = str(dep.get("line"))
#                 if line not in TRAM_LINES:
#                     continue

#                 dep_id = dep.get("id")
#                 dep_time = dep.get("departure", 0)
#                 dest = dep.get("dest", "Ismeretlen")

#                 veh = await fetch_json(session, VEHICLE_API.format(route=line, dep_id=dep_id))
#                 reg = get_last_vehicle_reg(veh)
#                 if not reg or not is_nos(reg):
#                     continue

#                 if reg not in active or dep_time < active[reg]["dep"]:
#                     active[reg] = {"line": line, "dest": dest, "stop": stop_id, "dep": dep_time}

#     if not active:
#         return await ctx.send("🚫 Ma nem közlekedik nosztalgia villamos. **Figyelem** a bot a __12__-es számú villamost nem látja, az lehet kint van.")

#     embed = discord.Embed(title="🚋 Aktív nosztalgia villamosok", color=0xffff00)
#     for reg, i in active.items():
#         embed.add_field(name=reg, value=f"Vonal: {i['line']}\nCél: {i['dest']}\nMegálló: {i['stop']}", inline=False)
#     await ctx.send(embed=embed)

@bot.command()
async def vehhist(ctx, vehicle: str, date: str = None):
    day = resolve_date(date)
    veh_file = f"logs/veh/{vehicle}.txt"

    if not os.path.exists(veh_file):
        return await ctx.send("❌ Nincs ilyen jármű a naplóban.")

    # --- beolvasás ---
    entries = []
    with open(veh_file, "r", encoding="utf-8") as f:
        for l in f:
            if not l.startswith(day):
                continue
            try:
                ts, rest = l.strip().split(" - ", 1)
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                trip_id = rest.split("ID ")[1].split(" ")[0]
                line = rest.split("Vonal ")[1].split(" ")[0]
                dest = rest.split(" - ")[-1]
                entries.append((dt, line, trip_id, dest))
            except:
                continue

    if not entries:
        return await ctx.send(f"❌ {vehicle} nem közlekedett ezen a napon ({day}).")

    # --- időrend ---
    entries.sort(key=lambda x: x[0])

    # --- menetek összevonása ---
    runs = []
    current = None

    for dt, line, trip_id, dest in entries:
        if (
            not current
            or trip_id != current["trip_id"]
            or line != current["line"]
        ):
            if current:
                runs.append(current)
            current = {
                "line": line,
                "trip_id": trip_id,
                "start": dt,
                "end": dt,
                "dest": dest
            }
        else:
            current["end"] = dt

    if current:
        runs.append(current)

    # --- KIÍRÁS (FÉLKÖVÉR!) ---
    lines = [f"🚎 {vehicle} – vehhist ({day})"]

    for r in runs:
        lines.append(
            f"{r['start'].strftime('%H:%M')} – "
            f"{r['line']} / {r['trip_id']} – "
            f"{r['dest']}"
        )

    msg = "\n".join(lines)

    # Discord limit
    for i in range(0, len(msg), 1900):
        await ctx.send(msg[i:i+1900])

@bot.command()
async def jaratinfo(ctx, trip_id: str, date: str = None):
    day = resolve_date(date)
    trip_path = f"logs/{day}/{trip_id}.txt"

    if os.path.exists(trip_path):
        with open(trip_path, "r", encoding="utf-8") as f:
            txt = f.read()
        return await ctx.send(f"📄 **Járat {trip_id} – {day}**\n```{txt[:1800]}```")

    found = []
    veh_dir = "logs/veh"
    for fname in os.listdir(veh_dir):
        path = os.path.join(veh_dir, fname)
        if not path.endswith(".txt"):
            continue
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(day) and f"ID {trip_id} " in line:
                    found.append((fname.replace(".txt",""), line.strip()))

    if not found:
        return await ctx.send(f"❌ Nincs adat erre a járatra ezen a napon ({day}).")

    out = [f"📄 Járat {trip_id} – {day}"]
    for veh, l in found:
        out.append(f"{veh}: {l}")

    msg = "\n".join(out)
    for i in range(0, len(msg), 1900):
        await ctx.send(msg[i:i+1900])

# # ───────────────────────────────
# # Ganz villamos
# # ───────────────────────────────
# @bot.command()
# async def bkvganztoday(ctx, date: str = None):
#     day = resolve_date(date)
#     veh_dir = "logs/veh"
#     active = {}

#     for fname in os.listdir(veh_dir):
#         if not fname.endswith(".txt"):
#             continue
#         reg = fname.replace(".txt", "")

#         if not is_ganz(reg) or is_ganz_troli(reg):
#             continue

#         with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
#             for line in f:
#                 if line.startswith(day):
#                     ts = line.split(" - ")[0]
#                     trip_id = line.split("ID ")[1].split(" ")[0]
#                     line_no = line.split("Vonal ")[1].split(" ")[0]
#                     line_name = LINE_MAP.get(line_no, line_no)
#                     active.setdefault(reg, []).append((ts, line_name, trip_id))

#     if not active:
#         return await ctx.send(f"🚫 {day} napon nem közlekedett Ganz.")

#     out = [f"🚊 Ganz – forgalomban ({day})"]
#     for reg in sorted(active):
#         first = min(active[reg], key=lambda x: x[0])
#         last = max(active[reg], key=lambda x: x[0])
#         out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

#     msg = "\n".join(out)
#     for i in range(0, len(msg), 1900):
#         await ctx.send(msg[i:i+1900])

# # ───────────────────────────────
# # TW6000
# # ───────────────────────────────
# @bot.command()
# async def bkvtw6000today(ctx, date: str = None):
#     day = resolve_date(date)
#     veh_dir = "logs/veh"
#     active = {}

#     for fname in os.listdir(veh_dir):
#         if not fname.endswith(".txt"):
#             continue
#         reg = fname.replace(".txt", "")

#         if not is_tw6000(reg):
#             continue

#         with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
#             for line in f:
#                 if line.startswith(day):
#                     ts = line.split(" - ")[0]
#                     trip_id = line.split("ID ")[1].split(" ")[0]
#                     line_no = line.split("Vonal ")[1].split(" ")[0]
#                     line_name = LINE_MAP.get(line_no, line_no)
#                     active.setdefault(reg, []).append((ts, line_name, trip_id))

#     if not active:
#         return await ctx.send(f"🚫 {day} napon nem közlekedett TW6000.")

#     out = [f"🚊 TW6000 – forgalomban ({day})"]
#     for reg in sorted(active):
#         first = min(active[reg], key=lambda x: x[0])
#         last = max(active[reg], key=lambda x: x[0])
#         out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

#     msg = "\n".join(out)
#     for i in range(0, len(msg), 1900):
#         await ctx.send(msg[i:i+1900])

# # ───────────────────────────────
# # Combino
# # ───────────────────────────────

# @bot.command()
# async def bkvcombinotoday(ctx, date: str = None):
#     day = resolve_date(date)
#     veh_dir = "logs/veh"
#     active = {}

#     for fname in os.listdir(veh_dir):
#         if not fname.endswith(".txt"):
#             continue
#         reg = fname.replace(".txt", "")

#         if not is_combino(reg):
#             continue

#         with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
#             for line in f:
#                 if line.startswith(day):
#                     ts = line.split(" - ")[0]
#                     trip_id = line.split("ID ")[1].split(" ")[0]
#                     line_no = line.split("Vonal ")[1].split(" ")[0]
#                     line_name = LINE_MAP.get(line_no, line_no)
#                     active.setdefault(reg, []).append((ts, line_name, trip_id))

#     if not active:
#         return await ctx.send(f"🚫 {day} napon nem közlekedett Combino.")

#     out = [f"🚊 Combino – forgalomban ({day})"]
#     for reg in sorted(active):
#         first = min(active[reg], key=lambda x: x[0])
#         last = max(active[reg], key=lambda x: x[0])
#         out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

#     msg = "\n".join(out)
#     for i in range(0, len(msg), 1900):
#         await ctx.send(msg[i:i+1900])

# # @bot.command()
# # async def bkvcombinotoday(ctx, date: str = None):
# #     day = resolve_date(date)
# #     data = today_data.get(day, {})

# #     # csak combino járművek
# #     active = {reg: trips for reg, trips in data.items() if is_combino(reg)}

# #     if not active:
# #         return await ctx.send(f"🚫 {day} napon nem közlekedett Combino.")

# #     out = [f"🚊 Combino – forgalomban ({day})"]
# #     for reg in sorted(active):
# #         first = min(active[reg], key=lambda x: x[0])
# #         last = max(active[reg], key=lambda x: x[0])
# #         out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

# #     msg = "\n".join(out)
# #     for i in range(0, len(msg), 1900):
# #         await ctx.send(msg[i:i+1900])

# # ───────────────────────────────
# # CAF (CAF5 + CAF9)
# # ───────────────────────────────
# @bot.command()
# async def bkvcaftoday(ctx, date: str = None):
#     day = resolve_date(date)
#     veh_dir = "logs/veh"
#     active = {}

#     for fname in os.listdir(veh_dir):
#         if not fname.endswith(".txt"):
#             continue
#         reg = fname.replace(".txt", "")

#         if not (is_caf5(reg) or is_caf9(reg)):
#             continue

#         with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
#             for line in f:
#                 if line.startswith(day):
#                     ts = line.split(" - ")[0]
#                     trip_id = line.split("ID ")[1].split(" ")[0]
#                     line_no = line.split("Vonal ")[1].split(" ")[0]
#                     line_name = LINE_MAP.get(line_no, line_no)
#                     active.setdefault(reg, []).append((ts, line_name, trip_id))

#     if not active:
#         return await ctx.send(f"🚫 {day} napon nem közlekedett CAF.")

#     out = [f"🚊 CAF – forgalomban ({day})"]
#     for reg in sorted(active):
#         first = min(active[reg], key=lambda x: x[0])
#         last = max(active[reg], key=lambda x: x[0])
#         out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

#     msg = "\n".join(out)
#     for i in range(0, len(msg), 1900):
#         await ctx.send(msg[i:i+1900])

# # ───────────────────────────────
# # Tatra
# # ───────────────────────────────
# @bot.command()
# async def bkvtatratoday(ctx, date: str = None):
#     day = resolve_date(date)
#     veh_dir = "logs/veh"
#     active = {}

#     for fname in os.listdir(veh_dir):
#         if not fname.endswith(".txt"):
#             continue
#         reg = fname.replace(".txt", "")

#         if not (is_t5c5(reg) or is_t5c5k2(reg)):
#             continue

#         with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
#             for line in f:
#                 if line.startswith(day):
#                     ts = line.split(" - ")[0]
#                     trip_id = line.split("ID ")[1].split(" ")[0]
#                     line_no = line.split("Vonal ")[1].split(" ")[0]
#                     line_name = LINE_MAP.get(line_no, line_no)
#                     active.setdefault(reg, []).append((ts, line_name, trip_id))

#     if not active:
#         return await ctx.send(f"🚫 {day} napon nem közlekedett Tatra.")

#     out = [f"🚊 Tatra – forgalomban ({day})"]
#     for reg in sorted(active):
#         first = min(active[reg], key=lambda x: x[0])
#         last = max(active[reg], key=lambda x: x[0])
#         out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

#     msg = "\n".join(out)
#     for i in range(0, len(msg), 1900):
#         await ctx.send(msg[i:i+1900])
        
# @bot.command()
# async def bkvclassictoday(ctx, date: str = None):
#     day = resolve_date(date)
#     veh_dir = "logs/veh"
#     active = {}

#     for fname in os.listdir(veh_dir):
#         if not fname.endswith(".txt"):
#             continue
#         reg = fname.replace(".txt", "")

#         if not is_t5c5(reg):
#             continue

#         with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
#             for line in f:
#                 if line.startswith(day):
#                     ts = line.split(" - ")[0]
#                     trip_id = line.split("ID ")[1].split(" ")[0]
#                     line_no = line.split("Vonal ")[1].split(" ")[0]
#                     line_name = LINE_MAP.get(line_no, line_no)
#                     active.setdefault(reg, []).append((ts, line_name, trip_id))

#     if not active:
#         return await ctx.send(f"🚫 {day} napon nem közlekedett Classic Tatra.")

#     out = [f"🚊 Classic Tatra – forgalomban ({day})"]
#     for reg in sorted(active):
#         first = min(active[reg], key=lambda x: x[0])
#         last = max(active[reg], key=lambda x: x[0])
#         out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

#     msg = "\n".join(out)
#     for i in range(0, len(msg), 1900):
#         await ctx.send(msg[i:i+1900])

# # ───────────────────────────────
# # Oktató villamos
# # ───────────────────────────────
# @bot.command()
# async def bkvtanulotoday(ctx, date: str = None):
#     day = resolve_date(date)
#     veh_dir = "logs/veh"
#     active = {}

#     for fname in os.listdir(veh_dir):
#         if not fname.endswith(".txt"):
#             continue
#         reg = fname.replace(".txt", "")

#         if not is_oktato(reg):
#             continue

#         with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
#             for line in f:
#                 if line.startswith(day):
#                     ts = line.split(" - ")[0]
#                     trip_id = line.split("ID ")[1].split(" ")[0]
#                     line_no = line.split("Vonal ")[1].split(" ")[0]
#                     line_name = LINE_MAP.get(line_no, line_no)
#                     active.setdefault(reg, []).append((ts, line_name, trip_id))

#     if not active:
#         return await ctx.send(f"🚫 {day} ma nem közlekedett oktató villamos.")

#     out = [f"🚊 Oktató – szabadon ({day})"]
#     for reg in sorted(active):
#         first = min(active[reg], key=lambda x: x[0])
#         last = max(active[reg], key=lambda x: x[0])
#         out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

#     msg = "\n".join(out)
#     for i in range(0, len(msg), 1900):
#         await ctx.send(msg[i:i+1900])
        
@bot.command()
async def vehicleinfo(ctx, vehicle: str):
    path = f"logs/veh/{vehicle}.txt"
    if not os.path.exists(path):
        return await ctx.send(f"❌ Nincs adat a(z) {vehicle} járműről.")

    with open(path, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]

    last = lines[-1]
    await ctx.send(f"🚊 **{vehicle} utolsó menete**\n```{last}```")
        
# @bot.command()
# async def bkvvillamostoday(ctx, date: str = None):
#     day = resolve_date(date)
#     veh_dir = "logs/veh"
#     active = {}

#     for fname in os.listdir(veh_dir):
#         if not fname.endswith(".txt"):
#             continue
#         reg = fname.replace(".txt", "")

#         # csak villamosok
#         if not (is_oktato(reg) or is_tw6000(reg) or is_combino(reg) or
#                 is_caf5(reg) or is_caf9(reg) or is_t5c5(reg) or "ganz" in reg.lower()):
#             continue

#         # Ganz troli kizárása
#         if is_ganz_troli(reg):
#             continue

#         with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
#             for line in f:
#                 if line.startswith(day):
#                     try:
#                         ts = line.split(" - ")[0]
#                         trip_id = line.split("ID ")[1].split(" ")[0]
#                         line_no = line.split("Vonal ")[1].split(" ")[0]
#                         line_name = LINE_MAP.get(line_no, line_no)
#                         active.setdefault(reg, []).append((ts, line_name, trip_id))
#                     except:
#                         continue

#     if not active:
#         return await ctx.send(f"🚫 {day} napon nem közlekedett villamos.")

#     out = [f"🚋 Villamos – szabadon ({day})"]
#     for reg in sorted(active):
#         first = min(active[reg], key=lambda x: x[0])
#         last = max(active[reg], key=lambda x: x[0])
#         out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

#     msg = "\n".join(out)
#     for i in range(0, len(msg), 1900):
#         await ctx.send(msg[i:i+1900])

@bot.command()
async def david(ctx, date: str = None):
    day = resolve_date(date)
    veh_dir = "logs/veh"
    active = {}

    target_vehicles = ["V4202", "V4289"]

    for fname in os.listdir(veh_dir):
        if not fname.endswith(".txt"):
            continue
        reg = fname.replace(".txt", "")
        if reg not in target_vehicles:
            continue

        with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(day):
                    try:
                        ts = line.split(" - ")[0]
                        trip_id = line.split("ID ")[1].split(" ")[0]
                        line_no = line.split("Vonal ")[1].split(" ")[0]
                        line_name = LINE_MAP.get(line_no, line_no)
                        active.setdefault(reg, []).append((ts, line_name, trip_id))
                    except:
                        continue

    if not active:
        return await ctx.send(f"🚫 {day} napon a V4202 és V4289 nem közlekedett.")

    out = [f"🚊 Járműfigyelés – David ({day})"]
    for reg in sorted(active):
        first = min(active[reg], key=lambda x: x[0])
        last = max(active[reg], key=lambda x: x[0])
        out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

    msg = "\n".join(out)
    for i in range(0, len(msg), 1900):
        await ctx.send(msg[i:i+1900])

# @bot.command()
# async def bkvpotlas(ctx):
#     active = {}

#     async with aiohttp.ClientSession() as session:
#         vehicles = await fetch_json(session, VEHICLES_API)
#         if not isinstance(vehicles, list):
#             return await ctx.send("❌ Nem érkezett adat az API-ból.")

#         for v in vehicles:
#             reg = v.get("license_plate")
#             model = (v.get("vehicle_model") or "").lower()
#             lat = v.get("latitude")
#             lon = v.get("longitude")
#             dest = v.get("destination", "Ismeretlen")
#             line_id = str(v.get("route_id", "—"))
#             line_name = LINE_MAP.get(line_id, line_id)

#             if not reg or lat is None or lon is None:
#                 continue

#             if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
#                 continue

#             # ─── pótlás típus ellenőrzés ───
#             if not any(t in model for t in POTLAS_TIPUSOK):
#                 continue

#             active[reg] = {
#                 "line": line_name,
#                 "dest": dest,
#                 "lat": lat,
#                 "lon": lon,
#                 "model": model
#             }

#     if not active:
#         return await ctx.send("🚫 Nincs aktív pótlásnak számító villamos.")

#     MAX_FIELDS = 20
#     embeds = []
#     embed = discord.Embed(
#         title="🚧 Aktív pótlásnak számító villamosok",
#         color=0xff0000
#     )
#     field_count = 0

#     for reg, i in sorted(active.items()):
#         if field_count >= MAX_FIELDS:
#             embeds.append(embed)
#             embed = discord.Embed(
#                 title="🚧 Aktív pótlásnak számító villamosok (folytatás)",
#                 color=0xff0000
#             )
#             field_count = 0

#         embed.add_field(
#             name=reg,
#             value=(
#                 f"🚋 **Típus:** {i['model']}\n"
#                 f"Vonal: {i['line']}\n"
#                 f"Cél: {i['dest']}\n"
#                 f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
#             ),
#             inline=False
#         )
#         field_count += 1

#     embeds.append(embed)
#     for e in embeds:
#         await ctx.send(embed=e)


# =======================
# START
# =======================

@bot.event
async def on_ready():
    if getattr(bot, "ready_done", False):
        return
    bot.ready_done = True

    ensure_dirs()        # könyvtárak létrehozása, ha kell
    print(f"Bejelentkezve mint {bot.user}")
    logger_loop.start()   # csak egyszer induljon el


bot.run(TOKEN)



