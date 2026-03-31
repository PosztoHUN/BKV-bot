import discord
from discord.ext import commands, tasks
import aiohttp
import os
import sys
import io
import csv
import zipfile
import asyncio
import requests
from datetime import datetime, timedelta
from collections import defaultdict

# =======================
# BEÁLLÍTÁSOK
# =======================

TOKEN = os.getenv("TOKEN")

VEHICLES_API = "https://holajarmu.hu/budapest/api/vehicles?city=budapest"

# TRAM_LINES = {
#     "3010", "3011", "3020", "3022", "3030", "3040", "3060", "3120", "3140",
#     "3170", "3190", "3230", "3240", "3280", "3281", "3370", "3371", "3410",
#     "3420", "3470", "3480", "3490", "3500", "3510", "3511", "3520", "3560",
#     "3561", "3590", "3591", "3592", "3600", "3610", "3620", "3621", "3690",
#     " ", "-", "9999", "9997", "R3180", "R3230", "R3360", "R3800", "R3118",
#     "N3560", "N3020", "N3180", "N3190", "N3600"
# }

LINE_EXCEPTIONS = {
    "3600": "60 Fogaskerekű",

    "R3180": "R18",
    "R3230": "R23",
    "R3360": "R36",
    "R3800": "R80",
    "R3118": "R118",

    "N3020": "N2",
    "N3180": "N18",
    "N3190": "N19",
    "N3560": "N56",
    "N3600": "N60",
    "N4700": "N70",
    "N4740": "N74",
    "N4767": "N76-79",
    
    "9999": "9999",
    "9997": "9997"
}

SUFFIX_MAP = {
    "0": "",
    "1": "A",
    "2": "B",
    "5": "E",
    "8": "G"
}

def decode_line(line_id: str) -> str:
    if not line_id:
        return "—"

    line_id = str(line_id)

    # 🔴 1. KIVÉTEL FELÜLÍR
    if line_id in LINE_EXCEPTIONS:
        return LINE_EXCEPTIONS[line_id]

    prefix = ""
    
    # 🔴 2. R / N kezelés
    if line_id.startswith(("R", "N")):
        prefix = line_id[0]
        core = line_id[1:]

        if not core.isdigit():
            return line_id

        # itt NINCS betű logika!
        line_number = int(core[1:])  # pl 3118 → 118
        return f"{prefix}{line_number}"

    # 🔴 3. normál 4 számjegy
    if not line_id.isdigit() or len(line_id) != 4:
        return line_id

    first = line_id[0]
    line_num = int(line_id[1:3])
    suffix_digit = line_id[3]

    # busz sávok
    if first in {"0", "1", "2", "9"}:
        if first == "1":
            line_num += 100
        elif first == "2":
            line_num += 200
        elif first == "9":
            line_num += 900

    # villamos (3) / troli (4) → sima 0-99
    elif first in {"3", "4"}:
        pass

    suffix = SUFFIX_MAP.get(suffix_digit, "")

    return f"{line_num}{suffix}"

POTLAS_TIPUSOK = {
    "t5c5",
    "t5c5k2",
    "ics",
    "kcsv7",
    "combino",
    "caf5",
    "caf9",
    "tw6000"
}

LOCK_FILE = "/tmp/discord_bot.lock"
DISCORD_LIMIT = 1900

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
# GTFS / HELYKITÖLTŐK
# =======================

GTFS_PATH = ""
TXT_URL = ""

TRIPS_META = {}
STOPS = {}
TRIP_START = {}
TRIP_STOPS = defaultdict(list)
SERVICE_DATES = defaultdict(dict)
ROUTES = defaultdict(lambda: defaultdict(list))

# =======================
# DISCORD INIT
# =======================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=".", intents=intents)

# =======================
# GTFS SEGÉD
# =======================

def open_gtfs(name):
    z = zipfile.ZipFile(GTFS_PATH)
    return io.TextIOWrapper(z.open(name), encoding="utf-8-sig")

def tsec(t):
    try:
        h, m, s = map(int, t.split(":"))
        return h * 3600 + m * 60 + s
    except Exception:
        return 10**9

def daily_forda_id(block_id):
    p = block_id.split("_")
    return f"{p[-3]}_{p[-2]}"

def forgalmi_from_dfid(dfid):
    try:
        return int(dfid.split("_")[-1])
    except Exception:
        return None

def service_active(service_id, date):
    return SERVICE_DATES.get(service_id, {}).get(date, False)

def load_gtfs():
    if not GTFS_PATH or not os.path.exists(GTFS_PATH):
        return

    with open_gtfs("trips.txt") as f:
        for r in csv.DictReader(f):
            TRIPS_META[r["trip_id"]] = r

    with open_gtfs("stops.txt") as f:
        for r in csv.DictReader(f):
            STOPS[r["stop_id"]] = r["stop_name"]

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

    try:
        with open_gtfs("calendar_dates.txt") as f:
            for r in csv.DictReader(f):
                date = datetime.strptime(r["date"], "%Y%m%d").date()
                if r["exception_type"] == "1":
                    SERVICE_DATES[r["service_id"]][date] = True
                elif r["exception_type"] == "2":
                    SERVICE_DATES[r["service_id"]][date] = False
    except Exception:
        pass

    for tid, t in TRIPS_META.items():
        bid = t.get("block_id")
        if not bid:
            continue
        rid = t["route_id"]
        dfid = daily_forda_id(bid)

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
            "headsign": t.get("trip_headsign", ""),
            "service_id": t.get("service_id", ""),
            "orig_block_id": bid,
            "first_stop": first_stop_name,
            "last_stop": last_stop_name,
            "first_time": first_time,
            "last_time": last_time
        })

    for rid in ROUTES:
        for dfid in ROUTES[rid]:
            ROUTES[rid][dfid].sort(key=lambda x: tsec(x["start_time"]))

def parse_txt_feed():
    if not TXT_URL:
        return {}

    try:
        text = requests.get(TXT_URL, timeout=10).text
    except Exception:
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
            msg = l + "\n\n"
        else:
            msg += l + "\n\n"
    if msg.strip():
        yield msg.rstrip()

# =======================
# SEGÉDFÜGGVÉNYEK
# =======================

def resolve_date(date_str=None):
    if not date_str:
        return datetime.now().date()

    date_str = str(date_str).lower()

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

last_seen = {}
LOG_INTERVAL = 300

def ensure_dirs():
    os.makedirs("logs", exist_ok=True)
    os.makedirs("logs/veh", exist_ok=True)

NOSZTALGIA = {"V4000", "V4171", "V4200", "V4349", "JARMU1", "JARMU2", "JARMU3", "T0309", "T0359"}

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
    if not reg.startswith("F"):
        return False
    num = "".join(c for c in reg if c.isdigit())
    if not num:
        return False
    return 50 <= int(num) <= 70

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
    if not isinstance(reg, str):
        return False
    if not reg.startswith("V"):
        return False
    if not reg[1:].isdigit():
        return False
    n = int(reg[1:])
    return 1301 <= n <= 1499

def is_kcsv7(reg):
    return reg in KCSV_NUMBERS

def is_ics(reg):
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

def is_ik280t(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("T0"):
        return False
    if not reg[2:].isdigit():
        return False
    n = int(reg[2:5])
    return 200 <= n <= 299

def is_ik412t(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("T0"):
        return False
    if not reg[2:].isdigit():
        return False
    n = int(reg[2:])
    return 700 <= n <= 714

def is_ik412gt(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("T0"):
        return False
    if not reg[2:].isdigit():
        return False
    n = int(reg[2:])
    return 720 <= n <= 721

def is_ik411t(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("T0"):
        return False
    if not reg[2:].isdigit():
        return False
    n = int(reg[2:])
    return 400 <= n <= 401

def is_gst(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("T0"):
        return False
    if not reg[2:].isdigit():
        return False
    n = int(reg[2:])
    return 601 <= n <= 626

def is_sst12iii(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("T"):
        return False
    if not reg[1:].isdigit():
        return False
    n = int(reg[1:])
    return 8000 <= n <= 8019

def is_sst18iii(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("T"):
        return False
    if not reg[1:].isdigit():
        return False
    n = int(reg[1:])
    return 9000 <= n <= 9015

def is_sst12iv(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("T"):
        return False
    if not reg[1:].isdigit():
        return False
    n = int(reg[1:])
    return 8100 <= n <= 8121

def is_sst18iv(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("T"):
        return False
    if not reg[1:].isdigit():
        return False
    n = int(reg[1:])
    return 9100 <= n <= 9149

async def fetch_json(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
            if r.status != 200:
                return None
            return await r.json()
    except Exception:
        return None

async def fetch_vehicles(session):
    data = await fetch_json(session, VEHICLES_API)
    if not isinstance(data, dict):
        return []
    vehicles = data.get("vehicles")
    if not isinstance(vehicles, list):
        return []
    return vehicles

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

    veh_file = f"logs/veh/{vehicle}.txt"
    key = f"{vehicle}_{trip_id}"

    write_log = False

    if key not in last_seen:
        write_log = True
    else:
        delta = (now - last_seen[key]).total_seconds()
        if delta >= LOG_INTERVAL:
            write_log = True

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

async def refresh_today_data(self):
    await self.wait_until_ready()
    while not self.is_closed():
        veh_dir = "logs/veh"
        today = datetime.now().date()
        data = {}

        if os.path.exists(veh_dir):
            for fname in os.listdir(veh_dir):
                if not fname.endswith(".txt"):
                    continue
                reg = fname.replace(".txt", "")
                if not is_combino(reg):
                    continue

                with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            ts_full = line.split(" - ")[0]
                            ts_date = datetime.strptime(ts_full, "%Y-%m-%d %H:%M:%S").date()
                            if ts_date != today:
                                continue

                            trip_id = line.split("ID ")[1].split(" ")[0]
                            line_no = line.split("Vonal ")[1].split(" ")[0]
                            line_name = decode_line(line_no)  # új rendszerhez igazítva
                            data.setdefault(reg, []).append((ts_full, line_name, trip_id))
                        except Exception:
                            continue

        today_data[today.strftime("%Y-%m-%d")] = data
        await asyncio.sleep(180)

@tasks.loop(minutes=3)
async def update_active_today():
    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)

        if not data:
            return

        vehicles = data.get("vehicles", [])

        active_today_villamos.clear()
        active_today_combino.clear()
        active_today_caf5.clear()
        active_today_caf9.clear()
        active_today_tatra.clear()

        for v in vehicles:
            reg = v.get("license_plate")
            line_id = str(v.get("route_id", "—"))
            line_name = decode_line(line_id)  # 🔥 EZ AZ ÚJ
            dest = v.get("label", "Ismeretlen")
            lat = v.get("lat")
            lon = v.get("lon")
            trip_id = str(v.get("trip_id") or v.get("vehicle_id") or "")
            model = (v.get("vehicle_model") or "").lower()

            if not reg or lat is None or lon is None:
                continue

            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            # 🔥 villamos felismerés marad
            if (
                "ganz" in model
                or is_tw6000(reg)
                or is_combino(reg)
                or is_caf5(reg)
                or is_caf9(reg)
                or is_t5c5(reg)
                or is_oktato(reg)
            ):
                if is_ganz_troli(reg):
                    continue

                now = datetime.utcnow()

                entry = active_today_villamos.setdefault(
                    reg,
                    {"line": line_name, "dest": dest, "first": None, "last": None}
                )

                if not entry["first"]:
                    entry["first"] = now
                entry["last"] = now

                # 🔽 típus bontás
                if is_combino(reg):
                    entry_c = active_today_combino.setdefault(
                        reg, {"line": line_name, "dest": dest, "first": None, "last": None}
                    )
                    if not entry_c["first"]:
                        entry_c["first"] = now
                    entry_c["last"] = now

                if is_caf5(reg):
                    entry_c = active_today_caf5.setdefault(
                        reg, {"line": line_name, "dest": dest, "first": None, "last": None}
                    )
                    if not entry_c["first"]:
                        entry_c["first"] = now
                    entry_c["last"] = now

                if is_caf9(reg):
                    entry_c = active_today_caf9.setdefault(
                        reg, {"line": line_name, "dest": dest, "first": None, "last": None}
                    )
                    if not entry_c["first"]:
                        entry_c["first"] = now
                    entry_c["last"] = now

                if is_t5c5(reg):
                    entry_c = active_today_tatra.setdefault(
                        reg, {"line": line_name, "dest": dest, "first": None, "last": None}
                    )
                    if not entry_c["first"]:
                        entry_c["first"] = now
                    entry_c["last"] = now

@tasks.loop(seconds=30)
async def logger_loop():
    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)

        if not data:
            return

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            try:
                reg = v.get("license_plate")
                lat = v.get("lat")
                lon = v.get("lon")
                line = str(v.get("route_id", "—"))
                dest = v.get("label", "Ismeretlen")

                # új API
                trip_id = str(v.get("trip_id") or v.get("vehicle_id") or "")

                if not reg or lat is None or lon is None:
                    continue

                if not in_bbox(lat, lon):
                    continue

                if not trip_id:
                    continue

                # 🔥 NINCS SEMMI SZŰRÉS
                save_trip(trip_id, line, reg, dest)

            except Exception:
                continue

# =======================
# PARANCSOK - Villamosok
# =======================

@bot.command()
async def bkvvillamos(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)

        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            line_id = str(v.get("route_id", "—"))
            line_name = decode_line(line_id)
            dest = v.get("label", "Ismeretlen")
            lat = v.get("lat")
            lon = v.get("lon")
            trip_id = str(v.get("trip_id") or v.get("vehicle_id") or "")
            model = (v.get("vehicle_model") or "").lower()

            if not reg or lat is None or lon is None:
                continue

            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            # 🔥 villamos szűrés
            if not (
                "ganz" in model
                or is_tw6000(reg)
                or is_combino(reg)
                or is_caf5(reg)
                or is_caf9(reg)
                or is_t5c5(reg)
                or is_t5c5k2(reg)
                or is_oktato(reg)
            ):
                continue

            if is_fogas(reg) or is_ganz_troli(reg):
                continue

            # 🔥 típus meghatározása
            if "ganz" in model and not is_tw6000(reg):
                vtype = "Ganz ICS"
            elif is_kcsv7(reg):
                vtype = "Ganz-Hunslet KCSV7"
            elif is_tw6000(reg):
                vtype = "Düwag TW6000"
            elif is_combino(reg):
                vtype = "Siemens Combino Supra NF12B"
            elif is_caf5(reg):
                vtype = "CAF Urbos 3 (5 modulos)"
            elif is_caf9(reg):
                vtype = "CAF Urbos 3 (9 modulos)"
            elif is_t5c5(reg):
                vtype = "Tatra T5C5"
            elif is_t5c5k2(reg):
                vtype = "Tatra-BKV T5C5K2"
            elif is_oktato(reg):
                vtype = "Oktató"
            else:
                vtype = "Ismeretlen"
                
            reg_num = reg[1:] if reg.startswith("V") and len(reg) == 5 else reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(title="🚋 Aktív villamosok", color=0xffff00)
    field_count = 0

    for reg, i in sorted(active.items()):
        forgalmi = menetrendi_forgalmi(i["trip_id"])

        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            # f"Forgalmi szám: {forgalmi}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title="🚋 Aktív villamosok (folytatás)", color=0xffff00)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)

    for e in embeds:
        await ctx.send(embed=e)

KIEMELT_VONALAK_TW = {"24", "28", "28A", "37", "37A", "51", "51A", "52", "62", "62A", "69", "9997", "9999", " ", "", "-"}
KIEMELT_VONALAK_ICS = {"2", "47", "48", "49", "9997", "9999", " ", "", "-"}
KIEMELT_VONALAK_KCSV7 = {"2", "2B", "23", "9997", "9999", " ", "", "-"}
KIEMELT_VONALAK_COMBINO = {"4", "6", "9997", "9999", " ", "", "-"}
KIEMELT_VONALAK_CAF9 = {"1", "9997", "9999", " ", "", "-"}
KIEMELT_VONALAK_CAF5 = {"3", "14", "17", "19", "42", "50", "56", "56A", "61", "69", "9997", "9999", " ", "", "-"}
KIEMELT_VONALAK_T5C5 = {"1", "1A", "9997", "9999", " ", "", "-"}
KIEMELT_VONALAK_T5C5K2 = {"1", "1A", "12", "14", "17", "19", "28", "28A", "37", "37A", "41", "56", "56A", "59", "59A", "59B", "61", "9997", "9999", " ", "", "-"}

@bot.command()
async def bkvkcsv7(ctx):
    active = {}
    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_vehicles(session)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            model = (v.get("vehicle_model") or "").lower()
            lat = v.get("lat")
            lon = v.get("lon")
            dest = v.get("label", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = decode_line(line_id)  # új rendszerhez igazítva

            if is_ganz_troli(reg) or is_ics(reg):
                continue
            if not reg or lat is None or lon is None:
                continue
            if "ganz" not in model:
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            # 🔹 rövidített azonosító
            reg_num = reg[1:] if reg.startswith("V") and len(reg) == 5 else reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Ganz KCSV7 villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(title="🚋 Aktív Ganz KCSV7 villamosok", color=0xffaa00)
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title="🚋 Aktív Ganz KCSV7 villamosok (folytatás)", color=0xffaa00)
            field_count = 0

        line = i["line"]
        line_text = f"🔴 *Vonal: {line}*" if line not in KIEMELT_VONALAK_KCSV7 else f"Vonal: {line}"

        embed.add_field(
            name=reg,  # már a rövidített azonosító
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
        vehicles = await fetch_vehicles(session)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            model = (v.get("vehicle_model") or "").lower()
            lat = v.get("lat")
            lon = v.get("lon")
            dest = v.get("label", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = decode_line(line_id)

            if is_ganz_troli(reg) or is_kcsv7(reg):
                continue
            if not reg or lat is None or lon is None:
                continue
            if "ganz" not in model:
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            reg_num = reg[1:] if reg.startswith("V") and len(reg) == 5 else reg
            active[reg_num] = {"line": line_name, "dest": dest, "lat": lat, "lon": lon}

    if not active:
        return await ctx.send("🚫 Nincs aktív Ganz ICS villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(title="🚋 Aktív Ganz ICS villamosok", color=0xffaa00)
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title="🚋 Aktív Ganz ICS villamosok (folytatás)", color=0xffaa00)
            field_count = 0

        line_text = f"🔴 *Vonal: {i['line']}*" if i['line'] not in KIEMELT_VONALAK_ICS else f"Vonal: {i['line']}"

        embed.add_field(
            name=reg,
            value=f"{line_text}\nCél: {i['dest']}\nPozíció: {i['lat']:.5f}, {i['lon']:.5f}",
            inline=False
        )
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)

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

@bot.command()
async def bkvtw6000(ctx):
    active = {}
    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_vehicles(session)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg_raw = v.get("license_plate")
            lat = v.get("lat")
            lon = v.get("lon")
            dest = v.get("label", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = decode_line(line_id)

            if not reg_raw or lat is None or lon is None:
                continue
            if not is_tw6000(reg_raw):
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            # Rövidített reg szám: V1301 -> 1301
            reg_num = reg_raw[1:] if reg_raw.startswith("V") and len(reg_raw) == 5 else reg_raw

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "lat": lat,
                "lon": lon,
                "fixlepcsos": is_fixlepcsos(reg_num)  # True/False
            }
    
    if not active:
        return await ctx.send("🚫 Nincs aktív TW6000-es villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(title="🚋 Aktív TW6000-es villamosok", color=0xffaa00)
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title="🚋 Aktív TW6000-es villamosok (folytatás)", color=0xffaa00)
            field_count = 0

        line_text = f"🔴 Vonal: *{i['line']}*" if i['line'] not in KIEMELT_VONALAK_TW else f"Vonal: {i['line']}"
        
        # Csak akkor írja ki, ha fixlépcsős
        fix_text = "Fixlépcsős" if i["fixlepcsos"] else ""

        embed.add_field(
            name=reg,
            value=(
                f"{line_text}\n"
                f"Cél: {i['dest']}\n"
                f"{fix_text}" + ("" if not fix_text else "\n") +
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)

@bot.command()
async def bkvcombino(ctx):
    active = {}
    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_vehicles(session)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            lat = v.get("lat")
            lon = v.get("lon")
            dest = v.get("label", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = decode_line(line_id)

            if not reg or lat is None or lon is None:
                continue
            if not is_combino(reg):
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            reg_num = reg[1:] if reg.startswith("V") and len(reg) == 5 else reg
            active[reg_num] = {"line": line_name, "dest": dest, "lat": lat, "lon": lon}

    if not active:
        return await ctx.send("🚫 Nincs aktív Combino villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed = discord.Embed(title="🚋 Aktív Combino villamosok", color=0xffff00)
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title="🚋 Aktív Combino villamosok (folytatás)", color=0xffff00)
            field_count = 0

        line_text = f"🔴 Vonal: *{i['line']}*" if i['line'] not in KIEMELT_VONALAK_COMBINO else f"Vonal: {i['line']}"

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
async def bkvoktato(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_vehicles(session)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            lat = v.get("lat")
            lon = v.get("lon")
            dest = v.get("label", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = decode_line(line_id)

            if not reg or lat is None or lon is None:
                continue
            if not is_oktato(reg):
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            reg_num = reg[1:] if reg.startswith("V") and len(reg) == 5 else reg
            active[reg_num] = {"line": line_name, "dest": dest, "lat": lat, "lon": lon}

    if not active:
        return await ctx.send("🚫 Nincs aktív Oktató villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚋 Aktív Oktató villamosok"
    embed = discord.Embed(title=embed_title_base, color=0xffaa00)
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0xffaa00)
            field_count = 0

        line_text = f"Vonal: {i['line']}"

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
async def bkvcaf5(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_vehicles(session)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            lat = v.get("lat")
            lon = v.get("lon")
            dest = v.get("label", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = decode_line(line_id)

            if not reg or lat is None or lon is None:
                continue
            if not is_caf5(reg):
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            reg_num = reg[1:] if reg.startswith("V") and len(reg) == 5 else reg
            active[reg_num] = {"line": line_name, "dest": dest, "lat": lat, "lon": lon}

    if not active:
        return await ctx.send("🚫 Nincs aktív CAF5 villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚋 Aktív CAF5 villamosok"
    embed = discord.Embed(title=embed_title_base, color=0xffff00)
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0xffff00)
            field_count = 0

        line_text = f"🔴 *Vonal: {i['line']}*" if i['line'] not in KIEMELT_VONALAK_CAF5 else f"Vonal: {i['line']}"

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
async def bkvcaf9(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_vehicles(session)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            lat = v.get("lat")
            lon = v.get("lon")
            dest = v.get("label", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = decode_line(line_id)

            if not reg or lat is None or lon is None:
                continue
            if not is_caf9(reg):
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            reg_num = reg[1:] if reg.startswith("V") and len(reg) == 5 else reg
            active[reg_num] = {"line": line_name, "dest": dest, "lat": lat, "lon": lon}

    if not active:
        return await ctx.send("🚫 Nincs aktív CAF9 villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚋 Aktív CAF9 villamosok"
    embed = discord.Embed(title=embed_title_base, color=0xffff00)
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0xffff00)
            field_count = 0

        line_text = f"🔴 *Vonal: {i['line']}*" if i['line'] not in KIEMELT_VONALAK_CAF9 else f"Vonal: {i['line']}"

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
async def bkvt5c5(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_vehicles(session)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            lat = v.get("lat")
            lon = v.get("lon")
            dest = v.get("label", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = decode_line(line_id)

            if not reg or lat is None or lon is None:
                continue
            if not is_t5c5(reg):
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            reg_num = reg[1:] if reg.startswith("V") and len(reg) == 5 else reg
            active[reg_num] = {"line": line_name, "dest": dest, "lat": lat, "lon": lon}

    if not active:
        return await ctx.send("🚫 Nincs aktív T5C5 villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚋 Aktív T5C5 villamosok"
    embed = discord.Embed(title=embed_title_base, color=0xffaa00)
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0xffaa00)
            field_count = 0

        line_text = f"🔴 *Vonal: {i['line']}*" if i['line'] not in KIEMELT_VONALAK_T5C5 else f"Vonal: {i['line']}"

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
async def bkvt5c5k2(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_vehicles(session)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            lat = v.get("lat")
            lon = v.get("lon")
            dest = v.get("label", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = decode_line(line_id)

            if not reg or lat is None or lon is None:
                continue
            if not is_t5c5k2(reg) or is_t5c5(reg):
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            reg_num = reg[1:] if reg.startswith("V") and len(reg) == 5 else reg
            active[reg_num] = {"line": line_name, "dest": dest, "lat": lat, "lon": lon}

    if not active:
        return await ctx.send("🚫 Nincs aktív T5C5K2 villamos.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚋 Aktív T5C5K2 villamosok"
    embed = discord.Embed(title=embed_title_base, color=0xffaa00)
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0xffaa00)
            field_count = 0

        line_text = f"🔴 *Vonal: {i['line']}*" if i['line'] not in KIEMELT_VONALAK_T5C5K2 else f"Vonal: {i['line']}"

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
async def bkvfogas(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_vehicles(session)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nem érkezett adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            lat = v.get("lat")
            lon = v.get("lon")
            dest = v.get("label", "Ismeretlen")
            line_id = str(v.get("route_id", "—"))
            line_name = decode_line(line_id)  # új rendszerhez igazítva

            if not reg or lat is None or lon is None:
                continue
            if not is_fogas(reg):
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            # F fogaskerekű azonosító rövidítése: F0051 -> 51
            reg_num = reg[-2:] if reg.startswith("F") and len(reg) == 5 else reg

            active[reg_num] = {"line": line_name, "dest": dest, "lat": lat, "lon": lon}

    if not active:
        return await ctx.send("🚫 Nincs aktív Fogaskerekű.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚋 Aktív Fogaskerekűek"
    embed = discord.Embed(title=embed_title_base, color=0xffff00)
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0xffff00)
            field_count = 0

        line_text = f"Vonal: {i['line']}"
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
        
        
# =======================
# PARANCSOK - Trolibuszok
# =======================
        
def normalize_troli_reg(reg):
    """
    Trolibusz regisztráció normalizálása:
    - Levágja a kezdő T-t
    - Megtartja a számokat 3-5 számjegyig
    """
    if not reg or not reg.startswith("T"):
        return reg
    digits = "".join(c for c in reg if c.isdigit())
    return str(int(digits))  # eltávolítja az esetleges vezető nullákat

@bot.command()
async def bkvtroli(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg or not reg.startswith("T"):
                continue  # csak T-vel kezdődő trolik

            line_id = str(v.get("route_id", "—"))
            line_name = decode_line(line_id)
            dest = v.get("label", "Ismeretlen")
            lat = v.get("lat")
            lon = v.get("lon")
            trip_id = str(v.get("trip_id") or v.get("vehicle_id") or "")
            model = (v.get("vehicle_model") or "").lower()

            if lat is None or lon is None:
                continue
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            # 🔥 trolibusz szűrés
            if not (
                "ganz" in model
                or is_ik280t(reg)
                or is_ik411t(reg)
                or is_ik412t(reg)
                or is_ik412gt(reg)
                or is_gst(reg)
                or is_sst12iii(reg)
                or is_sst12iv(reg)
                or is_sst18iii(reg)
                or is_sst18iv(reg)
            ):
                continue

            if is_fogas(reg) or is_ganz_troli(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if "ganz" in model and is_gst(reg):
                vtype = "Ganz-Solaris Trolino 12B"
            elif is_ik411t(reg):
                vtype = "Ikarus-Obus-Kiepe 411T"
            elif is_ik412t(reg):
                vtype = "Ikarus-Kiepe 412.81"
            elif is_ik412gt(reg):
                vtype = "Ikarus-BKV (GVM) 412.81GT"
            elif is_ik280t(reg):
                vtype = "Ikarus-GVM 280.94"
            elif is_sst12iii(reg):
                vtype = "Solaris-Škoda Trollino 12 gen. III"
            elif is_sst12iv(reg):
                vtype = "Solaris-Škoda Trollino 12 gen. IV"
            elif is_sst18iii(reg):
                vtype = "Solaris-Škoda Trollino 18 gen. III"
            elif is_sst18iv(reg):
                vtype = "Solaris-Škoda Trollino 18 gen. IV"
            else:
                vtype = "Ismeretlen"

            # 🔥 normalizált regisztráció számra
            digits = "".join(c for c in reg if c.isdigit())
            reg_num = str(int(digits)) if digits else reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív trolibusz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚋 Aktív trolibuszok"
    embed = discord.Embed(title=embed_title_base, color=0xff0000)
    field_count = 0

    for reg, i in sorted(active.items(), key=lambda x: int(x[0])):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0xff0000)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)

# =======================
# PARANCSOK - Egyébbek
# =======================

@bot.command()
async def vehhist(ctx, vehicle: str, date: str = None):
    day = resolve_date(date)
    if day is None:
        return await ctx.send("❌ Hibás dátumformátum. Használd így: `YYYY-MM-DD`")

    day_str = day.strftime("%Y-%m-%d")
    veh_file = f"logs/veh/{vehicle}.txt"

    if not os.path.exists(veh_file):
        return await ctx.send("❌ Nincs ilyen jármű a naplóban.")

    entries = []
    with open(veh_file, "r", encoding="utf-8") as f:
        for l in f:
            if not l.startswith(day_str):
                continue
            try:
                ts, rest = l.strip().split(" - ", 1)
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                trip_id = rest.split("ID ")[1].split(" ")[0]
                line = rest.split("Vonal ")[1].split(" ")[0]
                dest = rest.split(" - ")[-1]
                entries.append((dt, line, trip_id, dest))
            except Exception:
                continue

    if not entries:
        return await ctx.send(f"❌ {vehicle} nem közlekedett ezen a napon ({day_str}).")

    entries.sort(key=lambda x: x[0])

    runs = []
    current = None

    for dt, line, trip_id, dest in entries:
        if not current or trip_id != current["trip_id"] or line != current["line"]:
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

    lines = [f"🚎 {vehicle} – vehhist ({day_str})"]
    for r in runs:
        lines.append(f"{r['start'].strftime('%H:%M')} – {r['line']} / {r['trip_id']} – {r['dest']}")

    msg = "\n".join(lines)
    for i in range(0, len(msg), 1900):
        await ctx.send(msg[i:i + 1900])

@bot.command()
async def jaratinfo(ctx, trip_id: str, date: str = None):
    day = resolve_date(date)
    if day is None:
        return await ctx.send("❌ Hibás dátumformátum. Használd így: `YYYY-MM-DD`")

    day_str = day.strftime("%Y-%m-%d")
    trip_path = f"logs/{day_str}/{trip_id}.txt"

    if os.path.exists(trip_path):
        with open(trip_path, "r", encoding="utf-8") as f:
            txt = f.read()
        return await ctx.send(f"📄 **Járat {trip_id} – {day_str}**\n```{txt[:1800]}```")

    found = []
    veh_dir = "logs/veh"
    if os.path.exists(veh_dir):
        for fname in os.listdir(veh_dir):
            path = os.path.join(veh_dir, fname)
            if not path.endswith(".txt"):
                continue
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith(day_str) and f"ID {trip_id} " in line:
                        found.append((fname.replace(".txt", ""), line.strip()))

    if not found:
        return await ctx.send(f"❌ Nincs adat erre a járatra ezen a napon ({day_str}).")

    out = [f"📄 Járat {trip_id} – {day_str}"]
    for veh, l in found:
        out.append(f"{veh}: {l}")

    msg = "\n".join(out)
    for i in range(0, len(msg), 1900):
        await ctx.send(msg[i:i + 1900])

@bot.command()
async def vehicleinfo(ctx, vehicle: str):
    path = f"logs/veh/{vehicle}.txt"
    if not os.path.exists(path):
        return await ctx.send(f"❌ Nincs adat a(z) {vehicle} járműről.")

    with open(path, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]

    if not lines:
        return await ctx.send(f"❌ Nincs adat a(z) {vehicle} járműről.")

    last = lines[-1]
    await ctx.send(f"🚊 **{vehicle} utolsó menete**\n```{last}```")

@bot.command()
async def david(ctx, date: str = None):
    day = resolve_date(date)
    if day is None:
        return await ctx.send("❌ Hibás dátumformátum. Használd így: `YYYY-MM-DD`")

    day_str = day.strftime("%Y-%m-%d")
    veh_dir = "logs/veh"
    active = {}

    target_vehicles = ["V4202", "V4289"]

    if os.path.exists(veh_dir):
        for fname in os.listdir(veh_dir):
            if not fname.endswith(".txt"):
                continue
            reg = fname.replace(".txt", "")
            if reg not in target_vehicles:
                continue

            with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith(day_str):
                        try:
                            ts = line.split(" - ")[0]
                            trip_id = line.split("ID ")[1].split(" ")[0]
                            line_no = line.split("Vonal ")[1].split(" ")[0]
                            line_name = decode_line(line_no)  # új rendszerhez igazítva
                            active.setdefault(reg, []).append((ts, line_name, trip_id))
                        except Exception:
                            continue

    if not active:
        return await ctx.send(f"🚫 {day_str} napon a V4202 és V4289 nem közlekedett.")

    out = [f"🚊 Járműfigyelés – David ({day_str})"]
    for reg in sorted(active):
        first = min(active[reg], key=lambda x: x[0])
        last = max(active[reg], key=lambda x: x[0])
        out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

    msg = "\n".join(out)
    for i in range(0, len(msg), 1900):
        await ctx.send(msg[i:i + 1900])

# =======================
# START
# =======================

@bot.event
async def on_ready():
    if getattr(bot, "ready_done", False):
        return
    bot.ready_done = True

    ensure_dirs()
    print(f"Bejelentkezve mint {bot.user}")

    if not logger_loop.is_running():
        logger_loop.start()

    if not update_active_today.is_running():
        update_active_today.start()

if not TOKEN:
    print("Hiányzik a DISCORD_TOKEN környezeti változó.")
    sys.exit(1)

try:
    bot.run(TOKEN)
finally:
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception:
        pass