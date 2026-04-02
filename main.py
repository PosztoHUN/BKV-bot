from urllib import response

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
from supabase import create_client

# =======================
# BEÁLLÍTÁSOK
# =======================

TOKEN = os.getenv("TOKEN")

VEHICLES_API = "https://holajarmu.hu/budapest/api/vehicles?city=budapest"

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
    "N3581": "N58A",
    "N3600": "N60",
    "N4700": "N70",
    "N4740": "N74",
    "N4767": "N76-79",
    
    "9999": "9999",
    "9997": "9997"
}


# # 🔹 Supabase kapcsolat
# url = os.environ.get("SUPABASE_URL")
# key = os.environ.get("SUPABASE_KEY")
# supabase = create_client(url, key)

# 🔹 Suffix térkép
SUFFIX_MAP = {
    "0": "",
    "1": "A",
    "2": "B",
    "5": "E",
    "8": "G"
}

# # LINE_EXCEPTIONS lekérdezés a Supabase-ból
# def fetch_line_exceptions():
#     response = supabase.table("line_exceptions").select("*").execute()
#     print(response.data)
#     if response.data is None:
#         return {}
#     # kulcsok stringként
#     return {str(item["line_id"]).strip(): item["name"] for item in response.data}

# LINE_EXCEPTIONS = {str(item["line_id"]): item["name"] for item in response.data}

# # --- Funkciók ---
# def fetch_line_exceptions():
#     """Lekéri a line_exceptions táblát és frissíti a dictet."""
#     global LINE_EXCEPTIONS
#     try:
#         response = supabase.table("line_exceptions").select("*").execute()
#         # debug: kiírja a választ
#         print("Supabase response:", response)
#         # kompatibilitás: ha response.data nincs, nézd response.json()
#         data = getattr(response, "data", None)
#         if data is None:
#             # lehet, hogy dictként jön vissza
#             data = response if isinstance(response, list) else []
#         LINE_EXCEPTIONS = {str(item["line_id"]): item["name"] for item in data}
#         print("Frissített LINE_EXCEPTIONS:", LINE_EXCEPTIONS)
#     except Exception as e:
#         print("Hiba a lekérés során:", e)
#         LINE_EXCEPTIONS = {}

from supabase import create_client

import httpx

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

async def fetch_supabase_vehicles_async():
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(SUPABASE_URL, headers=headers, params={"select": "*"})
        resp.raise_for_status()
        data = resp.json()
        return {item["obuid"]: {"plate": item["plate"], "vtype": item["vtype"]} for item in data}

vehicles = asyncio.run(fetch_supabase_vehicles_async())
print(vehicles)

def decode_line(line_id: str) -> str:
    if not line_id:
        return "—"

    line_id = str(line_id)

    # 🔴 KIVÉTEL FELÜLÍR
    if line_id in LINE_EXCEPTIONS:
        return LINE_EXCEPTIONS[line_id]

    prefix = ""
    
    # 🔴 R / N kezelés
    if line_id.startswith(("R", "N")):
        prefix = line_id[0]
        core = line_id[1:]
        if not core.isdigit():
            return line_id
        # pl R3118 → 118
        line_number = int(core[-3:])  # mindig utolsó 3 számjegy
        return f"{prefix}{line_number}"

    # 🔴 normál 4 számjegy
    if line_id.isdigit() and len(line_id) == 4:
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
        suffix = SUFFIX_MAP.get(suffix_digit, "")
        return f"{line_num}{suffix}"

    # ha semmi nem illik
    return line_id

# # --- Fő loop ---
# def main_loop():
#     fetch_line_exceptions()
#     test_lines = ["3600", "R3180", "N3600", "9999", "3118", "4050"]

#     while True:
#         print("\n--- Dekódolt járatok ---")
#         for line in test_lines:
#             decoded = decode_line(line)
#             print(f"{line} → {decoded}")
#         # 24 órás sleep
#         print("\nVárakozás 24 órát az új frissítésig...")
#         time.sleep(24 * 60 * 60)
#         fetch_line_exceptions()

# if __name__ == "__main__":
#     main_loop()

# 🔹 Kódoló függvény
def encode_line(user_input: str) -> str:
    user_input = user_input.upper().strip()

    # 1️⃣ Kivételek ellenőrzése
    for k, v in LINE_EXCEPTIONS.items():
        if v.upper() == user_input:
            return k

    # 2️⃣ R / N vonalak
    if user_input.startswith(("R", "N")):
        prefix = user_input[0]
        num = user_input[1:]
        if num.isdigit():
            return f"{prefix}3{int(num):03d}"

    # 3️⃣ Suffix kezelés
    suffix = "0"
    base = user_input
    if user_input[-1].isalpha():
        base = user_input[:-1]
        for k, v in SUFFIX_MAP.items():
            if v == user_input[-1]:
                suffix = k
                break

    if not base.isdigit():
        return user_input

    num = int(base)

    # Troli
    if 70 <= num <= 83:
        return f"4{num:02d}{suffix}"

    # Busz (elsőbbség)
    if 5 <= num <= 99:
        return f"{num:03d}{suffix}"

    # Villamos
    if 1 <= num <= 69:
        return f"3{num:02d}{suffix}"

    # Minden más busz
    if 100 <= num <= 999:
        return f"{num:03d}{suffix}"

    return user_input

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

NOSZTALGIA = {"V4000", "V4171", "V4200", "V4349", "JARMU1", "JARMU2", "JARMU3", "T0309", "T0359", "BPI007", "BPI415", "BPI829", "BPI923", "BPO147", "BPO301", "BPO449", "BPO477", "AAIK405"}

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

def is_mbconiii(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - RVY601-620
    - RWA600
    - SKR801-832
    - AADI561-610
    - AADR701-722
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # RVY601-620
    if reg.startswith("RVY"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 601 <= int(digits) <= 620:
            return True

    # RWA600 (konkrét)
    if reg == "RWA600":
        return True

    # SKR801-832
    if reg.startswith("SKR"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 801 <= int(digits) <= 832:
            return True

    # AADI561-610
    if reg.startswith("AADI"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 561 <= int(digits) <= 610:
            return True

    # AADR701-722
    if reg.startswith("AADR"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 701 <= int(digits) <= 722:
            return True

    return False

def is_mbconiiig(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - RVY701-720
    - SKR721-737
    - AADI611-660
    - AADR751-763
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # RVY701-720
    if reg.startswith("RVY"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 701 <= int(digits) <= 720:
            return True

    # SKR721-737
    if reg.startswith("SKR"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 721 <= int(digits) <= 737:
            return True

    # AADI611-660
    if reg.startswith("AADI"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 611 <= int(digits) <= 660:
            return True

    # AADR751-763
    if reg.startswith("AADR"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 751 <= int(digits) <= 763:
            return True

    return False

def is_volvo7700a(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - FJX187-235
    - FKU901-950
    - FLR700-749
    - PON993
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # FJX187-235
    if reg.startswith("FJX"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 187 <= int(digits) <= 235:
            return True

    # FKU901-950
    if reg.startswith("FKU"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 901 <= int(digits) <= 950:
            return True

    # FLR700-749
    if reg.startswith("FLR"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 700 <= int(digits) <= 749:
            return True

    # PON993 (konkrét)
    if reg == "PON993":
        return True

    return False

def is_mbconii(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - NBW001-015
    - NWB351-365
    - PDB376-390
    - PKN601-631
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # NBW001-015
    if reg.startswith("NBW"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 1 <= int(digits) <= 15:
            return True

    # NWB351-365
    if reg.startswith("NWB"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 351 <= int(digits) <= 365:
            return True

    # PDB376-390
    if reg.startswith("PDB"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 376 <= int(digits) <= 390:
            return True

    # PKN601-631
    if reg.startswith("PKN"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 601 <= int(digits) <= 631:
            return True

    return False

def is_mbc2k(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - AOFL191-255
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # AOFL191-255
    if reg.startswith("AOFL"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 191 <= int(digits) <= 255:
            return True

    return False

def is_mbconiig(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    Tartományok:
    - NNE051-073
    - PDB701-731
    - SWF651-652
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # NNE051-073
    if reg.startswith("NNE"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 51 <= int(digits) <= 73:
            return True

    # PDB701-731
    if reg.startswith("PDB"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 701 <= int(digits) <= 731:
            return True

    # SWF651-652
    if reg.startswith("SWF"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 651 <= int(digits) <= 652:
            return True

    return False

def is_modulo108D(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    Tartományok:
    - NGC019-033
    - NHB034-036
    - NTM420-441
    - NTP537-546
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # NGC019-033
    if reg.startswith("NGC"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 19 <= int(digits) <= 33:
            return True

    # NHB034-036
    if reg.startswith("NHB"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 34 <= int(digits) <= 36:
            return True

    # NTM420-441
    if reg.startswith("NTM"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 420 <= int(digits) <= 441:
            return True

    # NTP537-546
    if reg.startswith("NTP"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 537 <= int(digits) <= 546:
            return True

    return False

def is_vhnew330cng(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    Tartományok / konkrét:
    - DPI206
    - MPW601-637
    - MUM638-647
    - SCD590-596
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # DPI206 (konkrét)
    if reg == "DPI206":
        return True

    # MPW601-637
    if reg.startswith("MPW"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 601 <= int(digits) <= 637:
            return True

    # MUM638-647
    if reg.startswith("MUM"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 638 <= int(digits) <= 647:
            return True

    # SCD590-596
    if reg.startswith("SCD"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 590 <= int(digits) <= 596:
            return True

    return False

def is_vhnewag300(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    Tartományok / konkrét:
    - MUT883-900
    - MUU901-907
    - RCT308-320
    - SIF014-015
    - SXE201-204
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # MUT883-900
    if reg.startswith("MUT"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 883 <= int(digits) <= 900:
            return True

    # MUU901-907
    if reg.startswith("MUU"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 901 <= int(digits) <= 907:
            return True

    # RCT308-320
    if reg.startswith("RCT"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 308 <= int(digits) <= 320:
            return True

    # SIF014-015
    if reg.startswith("SIF"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 14 <= int(digits) <= 15:
            return True

    # SXE201-204
    if reg.startswith("SXE"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 201 <= int(digits) <= 204:
            return True

    return False

def is_mbO530(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    Tartományok / konkrét:
    - LYH106-129
    - MMM133-136
    - NGC142-165
    - RTA297
    - AELH152
    - AOHZ844
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # LYH106-129
    if reg.startswith("LYH"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 106 <= int(digits) <= 129:
            return True

    # MMM133-136
    if reg.startswith("MMM"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 133 <= int(digits) <= 136:
            return True

    # NGC142-165
    if reg.startswith("NGC"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 142 <= int(digits) <= 165:
            return True

    # RTA297 (konkrét)
    if reg == "RTA297":
        return True

    # AELH152 (konkrét)
    if reg == "AELH152":
        return True

    # AOHZ844 (konkrét)
    if reg == "AOHZ844":
        return True

    return False

def is_volvo7700H(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - PHG621-648
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # PHG621-648
    if reg.startswith("PHG"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 621 <= int(digits) <= 648:
            return True

    return False

def is_volvo7700(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - MFW501-537
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # MFW501-537
    if reg.startswith("MFW"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 501 <= int(digits) <= 537:
            return True

    return False

def is_modulo168D(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - PMP911-921
    - SGY980-989
    - SVA736
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # PMP911-921
    if reg.startswith("PMP"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 911 <= int(digits) <= 921:
            return True

    # SGY980-989
    if reg.startswith("SGY"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 980 <= int(digits) <= 989:
            return True

    # SVA736 (konkrét)
    if reg == "SVA736":
        return True

    return False

def is_mbO530fG(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - PDZ830-837
    - SIF013
    - SKN824-826, 828-832
    - AILJ862-863
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # PDZ830-837
    if reg.startswith("PDZ"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 830 <= int(digits) <= 837:
            return True

    # SIF013 (konkrét)
    if reg == "SIF013":
        return True

    # SKN824-826 és 828-832 (827 kimarad)
    if reg.startswith("SKN"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits:
            n = int(digits)
            if (824 <= n <= 826) or (828 <= n <= 832):
                return True

    # AILJ862-863
    if reg.startswith("AILJ"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 862 <= int(digits) <= 863:
            return True

    return False

def is_ik127(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - PKD001-003
    - MXJ004-018
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # PKD001-003
    if reg.startswith("PKD"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 1 <= int(digits) <= 3:
            return True

    # MXJ004-018
    if reg.startswith("MXJ"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 4 <= int(digits) <= 18:
            return True

    return False

def is_karsan(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - NCV285-300
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # NCV285-300
    if reg.startswith("NCV"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 285 <= int(digits) <= 300:
            return True

    return False

def is_mbc2(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - AEHE426-427
    - AELD552-559
    - AILJ859-860
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # AEHE426-427
    if reg.startswith("AEHE"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 426 <= int(digits) <= 427:
            return True

    # AELD552-559
    if reg.startswith("AELD"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 552 <= int(digits) <= 559:
            return True

    # AILJ859-860
    if reg.startswith("AILJ"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 859 <= int(digits) <= 860:
            return True

    return False

def is_volvo7000(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - NCZ539-576
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # NCZ539-576
    if reg.startswith("NCZ"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 539 <= int(digits) <= 576:
            return True

    return False

def is_mbc2g(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - AELD560-569
    - AILJ864
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # AELD560-569
    if reg.startswith("AELD"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 560 <= int(digits) <= 569:
            return True

    # AILJ864 (konkrét)
    if reg == "AILJ864":
        return True

    return False

def is_vhag318(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - LOV853-881
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # LOV853-881
    if reg.startswith("LOV"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 853 <= int(digits) <= 881:
            return True

    return False

def is_volvo7900H(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - PHG651-658
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # PHG651-658
    if reg.startswith("PHG"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 651 <= int(digits) <= 658:
            return True

    return False

def is_mbO530f(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - SKN817-819, 821
    - AEGB791-792
    - AILJ861
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # SKN817-819, 821
    if reg.startswith("SKN"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits:
            n = int(digits)
            if (817 <= n <= 819) or (n == 821):
                return True

    # AEGB791-792
    if reg.startswith("AEGB"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 791 <= int(digits) <= 792:
            return True

    # AILJ861
    if reg == "AILJ861":
        return True

    return False

def is_moduloC68E(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - NLE848-860
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # NLE848-860
    if reg.startswith("NLE"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 848 <= int(digits) <= 860:
            return True

    return False

def is_urbIII10(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - MPV998-999
    - NAE996
    - SRN169-170
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # MPV998-999
    if reg.startswith("MPV"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 998 <= int(digits) <= 999:
            return True

    # NAE996 (konkrét)
    if reg == "NAE996":
        return True

    # SRN169-170
    if reg.startswith("SRN"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 169 <= int(digits) <= 170:
            return True

    return False

def is_vehixel(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - MXJ001-003
    - RCT269
    - RRH130
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # MXJ001-003
    if reg.startswith("MXJ"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 1 <= int(digits) <= 3:
            return True

    # RCT269 (konkrét)
    if reg == "RCT269":
        return True

    # RRH130 (konkrét)
    if reg == "RRH130":
        return True

    return False

def is_mbO530K(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - AILJ856-858
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # AILJ856-858
    if reg.startswith("AILJ"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 856 <= int(digits) <= 858:
            return True

    return False

def is_eurosprinter(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - REM813
    - SKN814
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # REM813 (konkrét)
    if reg == "REM813":
        return True

    # SKN814 (konkrét)
    if reg == "SKN814":
        return True

    return False

def is_mbO530G(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - PCC933-934
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # PCC933-934
    if reg.startswith("PCC"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits and 933 <= int(digits) <= 934:
            return True

    return False

def is_urbIII8(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - AAMD172-173
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # AAMD172-173
    if reg.startswith("AAMD"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 172 <= int(digits) <= 173:
            return True

    return False

def is_vhnewa330(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - MKL981
    - PDN684
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # MKL981 (konkrét)
    if reg == "MKL981":
        return True

    # PDN684 (konkrét)
    if reg == "PDN684":
        return True

    return False

def is_ik187(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - MDD721
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # MDD721 (konkrét)
    if reg == "MDD721":
        return True

    return False

def is_itkreform(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - CITY001
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # CITY001 (konkrét)
    if reg == "CITY001":
        return True

    return False

def is_sprinter65(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - PJZ072
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # PJZ072 (konkrét)
    if reg == "PJZ072":
        return True

    return False

def is_citymax(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - RCT219
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # RCT219 (konkrét)
    if reg == "RCT219":
        return True

    return False

def is_bydb12(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - AOIA470-477
    - AOIB790-811
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # AOIA470-477
    if reg.startswith("AOIA"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits:
            n = int(digits)
            if (470 <= n <= 477):
                return True

    # AOIB790-811
    if reg.startswith("AOIB"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 790 <= int(digits) <= 811:
            return True

    return False

def is_bydb19(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - AOIB820-826
    - AONW951-967
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # AOIB820-826
    if reg.startswith("AOIB"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits:
            n = int(digits)
            if (820 <= n <= 826):
                return True

    # AONW951-967
    if reg.startswith("AONW"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits and 951 <= int(digits) <= 967:
            return True

    return False

def is_arrivacon(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - NCA401-532
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # NCA401-532
    if reg.startswith("NCA"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits:
            n = int(digits)
            if (401 <= n <= 532):
                return True

    return False

def is_arrivac2(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - AOCT651-677
    - AOGF651-780
    - AOIM001-056
    - AOJM860-886
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # AOCT651-677
    if reg.startswith("AOCT"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits:
            n = int(digits)
            if (651 <= n <= 677):
                return True
            
    # AOGF651-780
    if reg.startswith("AOGF"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits:
            n = int(digits)
            if (651 <= n <= 780):
                return True
            
    # AOIM001-056
    if reg.startswith("AOIM"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits:
            n = int(digits)  # int automatikusan kezeli az esetleges 0-kat
            if 1 <= n <= 56:  # ❌ vezető nullák nélkül
                return True
            
    # AOJM860-886
    if reg.startswith("AOJM"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits:
            n = int(digits)
            if (860 <= n <= 886):
                return True

    return False

def is_arriva12c(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - AAHY801-881
    - AOGL301-325
    - AOLH517-518
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # AAHY801-881
    if reg.startswith("AAHY"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits:
            n = int(digits)
            if (801 <= n <= 881):
                return True
            
    # AOGL301-325
    if reg.startswith("AOGL"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits:
            n = int(digits)
            if (301 <= n <= 325):
                return True
            
    # AOLH517-518
    if reg.startswith("AOLH"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits:
            n = int(digits)
            if (517 <= n <= 518):
                return True

    return False

def is_arriva18c(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - AAMH601-681
    - AOLH515-516
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # AAMH601-681
    if reg.startswith("AAMH"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits:
            n = int(digits)
            if (601 <= n <= 681):
                return True

    # AOLH515-516
    if reg.startswith("AOLH"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits:
            n = int(digits)
            if (515 <= n <= 516):
                return True

    return False

def is_arrivaa21(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - NAY301-382
    - PDN601-650
    - SGY801-824
    - VTA641
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # NAY301-382
    if reg.startswith("NAY"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits:
            n = int(digits)
            if (301 <= n <= 382):
                return True

    # PDN601-650
    if reg.startswith("PDN"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits:
            n = int(digits)
            if (601 <= n <= 650):
                return True

    # SGY801-824
    if reg.startswith("SGY"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits:
            n = int(digits)
            if (801 <= n <= 824):
                return True

    # VTA641
    if reg.startswith("VTA"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits:
            n = int(digits)
            if (641 == n):
                return True

    return False

def is_vol12c(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - AAGL250-324
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # AAGL250-324
    if reg.startswith("AAGL"):
        digits = ''.join(c for c in reg[4:] if c.isdigit())
        if digits:
            n = int(digits)
            if (250 <= n <= 324):
                return True

    return False

def is_vol7900a(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - MOS283-299
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # MOS283-299
    if reg.startswith("MOS"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits:
            n = int(digits)
            if (283 <= n <= 299):
                return True

    return False

def is_volcon(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - RVY721-750
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace("", "").replace("", "")

    # RVY721-750
    if reg.startswith("RVY"):
        digits = ''.join(c for c in reg[3:] if c.isdigit())
        if digits:
            n = int(digits)
            if (721 <= n <= 750):
                return True

    return False

def is_obu(reg):
    """
    Ellenőrzi, hogy a regisztráció a cél járművek közé tartozik:
    - JARMU1-8
    """
    if not isinstance(reg, str):
        return False
    reg = reg.upper().replace(" ", "").replace("-", "")

    # JARMU1-8
    if reg.startswith("JARMU"):
        digits = ''.join(c for c in reg[5:] if c.isdigit())
        if digits and 1 <= int(digits) <= 8:
            return True

    return False

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
async def bkvtanulo(ctx):
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

            # 🔥 EZ LETT A SZŰRÉS
            if dest != "Tanulójárat":
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
        return await ctx.send("🚫 Nincs aktív Tanulójárat.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚋 Aktív Tanulójáratok"
    embed = discord.Embed(title=embed_title_base, color=0xffaa00)
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0xffaa00)
            field_count = 0

        embed.add_field(
            name=reg,
            value=(
                f"Vonal: {i['line']}\n"
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
                is_ganz_troli(reg)           # Ganz trolik T0601-T0626
                or is_ik280t(reg)
                or is_ik411t(reg)
                or is_ik412t(reg)
                or is_ik412gt(reg)
                or is_sst12iii(reg)
                or is_sst12iv(reg)
                or is_sst18iii(reg)
                or is_sst18iv(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_ganz_troli(reg):
                vtype = "Ganz-Solaris Trolino 12B"
                if reg in {"T0607", "T0608", "T0609", "T0610", "T0611", "T0612", "T0613", "T0614", "T0615", "T0616"}:
                    vtype = "Ganz-Škoda-Solaris Trolino 12B"
                elif reg in {"T0620", "T0621", "T0622", "T0623", "T0624", "T0625", "T0626"}:
                    vtype = "Ganz-Škoda-Solaris Trolino 12D"
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
    embed_title_base = "🚎 Aktív trolibuszok"
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

@bot.command()
async def bkviktroli(ctx):
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
                is_ik280t(reg)
                or is_ik411t(reg)
                or is_ik412t(reg)
                or is_ik412gt(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_ik411t(reg):
                vtype = "Ikarus-Obus-Kiepe 411T"
            elif is_ik412t(reg):
                vtype = "Ikarus-Kiepe 412.81"
            elif is_ik412gt(reg):
                vtype = "Ikarus-BKV (GVM) 412.81GT"
            elif is_ik280t(reg):
                vtype = "Ikarus-GVM 280.94"
            else:
                vtype = "Ismeretlen"

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
        return await ctx.send("🚫 Nincs aktív Ikarus trolibusz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚎 Aktív Ikarus trolibuszok"
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
        
@bot.command()
async def bkvgst(ctx):
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
                is_ganz_troli(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_ganz_troli(reg):
                vtype = "Ganz-Solaris Trolino 12B"
                if reg in {"T0607", "T0608", "T0609", "T0610", "T0611", "T0612", "T0613", "T0614", "T0615", "T0616"}:
                    vtype = "Ganz-Škoda-Solaris Trolino 12B"
                elif reg in {"T0620", "T0621", "T0622", "T0623", "T0624", "T0625", "T0626"}:
                    vtype = "Ganz-Škoda-Solaris Trolino 12D"
            else:
                vtype = "Ismeretlen"

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
        return await ctx.send("🚫 Nincs aktív GST trolibusz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚎 Aktív GST trolibuszok"
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
        
@bot.command()
async def bkvsst(ctx):
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
                is_sst12iii(reg)
                or is_sst12iv(reg)
                or is_sst18iii(reg)
                or is_sst18iv(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_sst12iii(reg):
                vtype = "Solaris-Škoda Trollino 12 gen. III"
            elif is_sst12iv(reg):
                vtype = "Solaris-Škoda Trollino 12 gen. IV"
            elif is_sst18iii(reg):
                vtype = "Solaris-Škoda Trollino 18 gen. III"
            elif is_sst18iv(reg):
                vtype = "Solaris-Škoda Trollino 18 gen. IV"
            else:
                vtype = "Ismeretlen"

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
        return await ctx.send("🚫 Nincs aktív Solaris trolibusz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚎 Aktív Solaris trolibuszok"
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
# PARANCSOK - Buszok
# =======================

@bot.command()
async def bkvvolvo(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue  # nincs rendszám

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

            # 🔥 Volvo busz szűrés
            if not (
                is_volvo7000(reg)
                or is_volvo7700(reg)
                or is_volvo7700a(reg)
                or is_volvo7700H(reg)
                or is_volvo7900H(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_volvo7000(reg):
                vtype = "Volvo 7000"
            elif is_volvo7700(reg):
                vtype = "Volvo 7700"
            elif is_volvo7700a(reg):
                vtype = "Volvo 7700A"
            elif is_volvo7700H(reg):
                vtype = "Volvo 7700 Hybrid"
            elif is_volvo7900H(reg):
                vtype = "Volvo 7900 Hybrid"
            else:
                vtype = "Ismeretlen"

            # megtartjuk a teljes rendszámot betűkkel együtt
            reg_num = reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Volvo busz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚌 Aktív Volvo buszok"
    embed = discord.Embed(title=embed_title_base, color=0x0000ff)
    field_count = 0

    # 🔹 rendszám szerint ábécé sorrendben
    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x0000ff)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)
        
@bot.command()
async def bkvconecto(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue  # nincs rendszám

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

            # 🔥 Mercedes busz szűrés
            if not (
                is_mbconii(reg)
                or is_mbconiig(reg)
                or is_mbconiii(reg)
                or is_mbconiiig(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_mbconii(reg):
                vtype = "Mercedes-Benz Conecto II"
            elif is_mbconiig(reg):
                vtype = "Mercedes-Benz Conecto II G"
            elif is_mbconiii(reg):
                vtype = "Mercedes-Benz Conecto III"
            elif is_mbconiiig(reg):
                vtype = "Mercedes-Benz Conecto III G"
            else:
                vtype = "Ismeretlen"

            # megtartjuk a teljes rendszámot betűkkel együtt
            reg_num = reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Conecto busz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚌 Aktív Conecto buszok"
    embed = discord.Embed(title=embed_title_base, color=0x0000ff)
    field_count = 0

    # 🔹 rendszám szerint ábécé sorrendben
    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x0000ff)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)
        
@bot.command()
async def bkvc1(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue  # nincs rendszám

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

            # 🔥 Mercedes busz szűrés
            if not (
                is_mbO530(reg)
                or is_mbO530f(reg)
                or is_mbO530fG(reg)
                or is_mbO530G(reg)
                or is_mbO530K(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_mbO530(reg):
                vtype = "Mercedes-Benz O530"
            elif is_mbO530f(reg):
                vtype = "Mercedes-Benz O530 facelift"
            elif is_mbO530fG(reg):
                vtype = "Mercedes-Benz O530G facelift"
            elif is_mbO530G(reg):
                vtype = "Mercedes-Benz O530G"
            elif is_mbO530K(reg):
                vtype = "Mercedes-Benz O530K"
            else:
                vtype = "Ismeretlen"

            # megtartjuk a teljes rendszámot betűkkel együtt
            reg_num = reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Citaro C1 busz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚌 Aktív Citaro C1 buszok"
    embed = discord.Embed(title=embed_title_base, color=0x0000ff)
    field_count = 0

    # 🔹 rendszám szerint ábécé sorrendben
    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x0000ff)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)
        
@bot.command()
async def bkvc2(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue  # nincs rendszám

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

            # 🔥 Mercedes busz szűrés
            if not (
                is_mbc2(reg)
                or is_mbc2g(reg)
                or is_mbc2k(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_mbc2(reg):
                vtype = "Mercedes-Benz C2"
            elif is_mbc2g(reg):
                vtype = "Mercedes-Benz C2G"
            elif is_mbc2k(reg):
                vtype = "Mercedes-Benz C2K"
            else:
                vtype = "Ismeretlen"

            # megtartjuk a teljes rendszámot betűkkel együtt
            reg_num = reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Citaro C2 busz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚌 Aktív Citaro C2 buszok"
    embed = discord.Embed(title=embed_title_base, color=0x0000ff)
    field_count = 0

    # 🔹 rendszám szerint ábécé sorrendben
    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x0000ff)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)   
        
@bot.command()
async def bkvmodulo(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue  # nincs rendszám

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

            # 🔥 Mercedes busz szűrés
            if not (
                is_modulo108D(reg)
                or is_modulo168D(reg)
                or is_moduloC68E(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_modulo108D(reg):
                vtype = "MABI Modulo M108D"
            elif is_modulo168D(reg):
                vtype = "MABI Modulo M168D"
            elif is_moduloC68E(reg):
                vtype = "MABI Modulo MC68E"
            else:
                vtype = "Ismeretlen"

            # megtartjuk a teljes rendszámot betűkkel együtt
            reg_num = reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Modulo busz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚌 Aktív Modulo buszok"
    embed = discord.Embed(title=embed_title_base, color=0x0000ff)
    field_count = 0

    # 🔹 rendszám szerint ábécé sorrendben
    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x0000ff)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)   
        
        
@bot.command()
async def bkvvanhool(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue  # nincs rendszám

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

            # 🔥 Mercedes busz szűrés
            if not (
                is_vhag318(reg)
                or is_vhnew330cng(reg)
                or is_vhnewa330(reg)
                or is_vhnewag300(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_vhag318(reg):
                vtype = "VanHool AG318"
            elif is_vhnew330cng(reg):
                vtype = "VanHool newA330 CNG"
            elif is_vhnewa330(reg):
                vtype = "VanHool newA330"
            elif is_vhnewag300(reg):
                vtype = "VanHool newAG300"
            else:
                vtype = "Ismeretlen"

            # megtartjuk a teljes rendszámot betűkkel együtt
            reg_num = reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív VanHool busz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚌 Aktív VanHool buszok"
    embed = discord.Embed(title=embed_title_base, color=0x0000ff)
    field_count = 0

    # 🔹 rendszám szerint ábécé sorrendben
    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x0000ff)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)   
        
@bot.command()
async def bkvik(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue  # nincs rendszám

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

            # 🔥 Mercedes busz szűrés
            if not (
                is_ik127(reg)
                or is_ik187(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_ik127(reg):
                vtype = "Ikarus V127"
            elif is_ik187(reg):
                vtype = "Ikarus V187"
            else:
                vtype = "Ismeretlen"

            # megtartjuk a teljes rendszámot betűkkel együtt
            reg_num = reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Ikarus busz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚌 Aktív Ikarus buszok"
    embed = discord.Embed(title=embed_title_base, color=0x0000ff)
    field_count = 0

    # 🔹 rendszám szerint ábécé sorrendben
    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x0000ff)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)   
        
@bot.command()
async def bkvmidi(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue  # nincs rendszám

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

            # 🔥 Mercedes busz szűrés
            if not (
                is_karsan(reg)
                or is_moduloC68E(reg)
                or is_urbIII10(reg)
                or is_urbIII8(reg)
                or is_vehixel(reg) 
                or is_eurosprinter(reg)
                or is_itkreform(reg)
                or is_sprinter65(reg)
                or is_citymax(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_karsan(reg):
                vtype = "Karsan Atak"
            elif is_moduloC68E(reg):
                vtype = "MABI Modulo C68E"
            elif is_urbIII10(reg):
                vtype = "Solaris Urbino III 10"
            elif is_urbIII8(reg):
                vtype = "Solaris Urbino III 8"
            elif is_vehixel(reg):
                vtype = "Vehixel Cytios 3/23"
            elif is_eurosprinter(reg):
                vtype = "Euro Limbus Sprinter"
            elif is_itkreform(reg):
                vtype = "ITK Reform-S City Max"
            elif is_sprinter65(reg):
                vtype = "Mercedes-Benz Sprinter City 65"
            elif is_citymax(reg):
                vtype = "TS City Max"
            else:
                vtype = "Ismeretlen"

            # megtartjuk a teljes rendszámot betűkkel együtt
            reg_num = reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív midi busz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚌 Aktív midi buszok"
    embed = discord.Embed(title=embed_title_base, color=0x0000ff)
    field_count = 0

    # 🔹 rendszám szerint ábécé sorrendben
    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x0000ff)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)   
        
@bot.command()
async def arrivabyd(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue  # nincs rendszám

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

            # 🔥 Mercedes busz szűrés
            if not (
                is_bydb12(reg)
                or is_bydb19(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_bydb12(reg):
                vtype = "BYD B12E03 (B12.b)"
            elif is_bydb19(reg):
                vtype = "BYD B19E01"
            else:
                vtype = "Ismeretlen"

            # megtartjuk a teljes rendszámot betűkkel együtt
            reg_num = reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív BYD busz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚌 Aktív BYD buszok"
    embed = discord.Embed(title=embed_title_base, color=0x0000ff)
    field_count = 0

    # 🔹 rendszám szerint ábécé sorrendben
    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x0000ff)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)    
        
@bot.command()
async def arrivaconecto(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue  # nincs rendszám

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

            # 🔥 Mercedes busz szűrés
            if not (
                is_arrivacon(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_arrivacon(reg):
                vtype = "Mercedes-Benz Conecto II G"
            else:
                vtype = "Ismeretlen"

            # megtartjuk a teljes rendszámot betűkkel együtt
            reg_num = reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Conecto busz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚌 Aktív Conecto buszok"
    embed = discord.Embed(title=embed_title_base, color=0x0000ff)
    field_count = 0

    # 🔹 rendszám szerint ábécé sorrendben
    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x0000ff)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)  
        
@bot.command()
async def arrivaman(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue  # nincs rendszám

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

            # 🔥 Mercedes busz szűrés
            if not (
                is_arrivaa21(reg)
                or is_arriva18c(reg)
                or is_arriva12c(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_arrivaa21(reg):
                vtype = "MAN A21 Lion's City NL283"
            elif is_arriva12c(reg):
                vtype = "MAN 12C Lion's City 12 NL280"
            elif is_arriva18c(reg):
                vtype = "MAN 18C Lion's City 18 NG330"
            else:
                vtype = "Ismeretlen"

            # megtartjuk a teljes rendszámot betűkkel együtt
            reg_num = reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív MAN busz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚌 Aktív MAN buszok"
    embed = discord.Embed(title=embed_title_base, color=0x0000ff)
    field_count = 0

    # 🔹 rendszám szerint ábécé sorrendben
    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x0000ff)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)  
        
@bot.command()
async def arrivac2(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue  # nincs rendszám

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

            # 🔥 Mercedes busz szűrés
            if not (
                is_arrivac2(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus meghatározása
            if is_arrivac2(reg):
                vtype = "Mercedes-Benz Citaro C2"
            else:
                vtype = "Ismeretlen"

            # megtartjuk a teljes rendszámot betűkkel együtt
            reg_num = reg

            active[reg_num] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Citaro C2 busz.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚌 Aktív Citaro C2 buszok"
    embed = discord.Embed(title=embed_title_base, color=0x0000ff)
    field_count = 0

    # 🔹 rendszám szerint ábécé sorrendben
    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x0000ff)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)    
        
@bot.command()
async def aggvolan(ctx):
    active = {}

    # Supabase járművek lekérése aszinkron
    supa_vehicles = await fetch_supabase_vehicles_async()
    
    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue  # nincs rendszám

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

            # 🔥 Mercedes busz szűrés
            if not (
                is_vol12c(reg)
                or is_volcon(reg)
                or is_vol7900a(reg)
                or is_obu(reg)
            ):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus és megjelenítendő rendszám Supabase alapján
            display_reg = reg
            if is_volcon(reg):
                vtype = "Mercedes-Benz Conecto III G"
            elif is_vol12c(reg):
                vtype = "MAN 12C Lion's City 12 G NL320"
            elif is_vol7900a(reg):
                vtype = "Volvo 7900A"
            elif is_obu(reg):
                if reg in ["JARMU1", "JARMU2", "JARMU3"]:
                    continue  # kihagyjuk
                elif reg in ["JARMU4", "JARMU5", "JARMU6", "JARMU7", "JARMU8"]:
                    if reg in supa_vehicles:
                        vtype = supa_vehicles[reg]["vtype"]
                        display_reg = f"{supa_vehicles[reg]['plate']} ({reg})"
                    else:
                        vtype = "VOLVO 7900A"
                        display_reg = f"{reg} ({reg})"
                else:
                    vtype = "Ismeretlen"
            else:
                vtype = "Ismeretlen"

            active[display_reg] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív agglomerációs volánbusz.")

    # Embed küldés
    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚌 Aktív agglomerációs volánbuszok"
    embed = discord.Embed(title=embed_title_base, color=0x0000ff)
    field_count = 0

    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x0000ff)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)
        
# =======================
# PARANCSOK - Egyébbek
# =======================

# Segédfüggvény a vonal OP-szűréshez
def is_op_line(line_id):
    return line_id.upper().startswith("OP")

# Automatikus 5 perces küldés
from discord.ext import commands, tasks
import discord
import aiohttp
import asyncio

BOT_CHANNEL_ID = 1461491191328673822  # cél csatorna ID
MAX_FIELDS = 20

# Globális tároló a korábbi embedekhez és járműadatokhoz
last_active = {}
embed_messages = []

async def fetch_json(session, url):
    async with session.get(url) as resp:
        if resp.status == 200:
            return await resp.json()
        return None

def is_op_line(line_id):
    return str(line_id).upper().startswith("OP")

@tasks.loop(minutes=5)
async def send_op_vehicles():
    # a loop tartalma ugyanaz
    global last_active, embed_messages

    channel = bot.get_channel(BOT_CHANNEL_ID)
    if not channel:
        return

    active = {}
    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            await channel.send("❌ Nem sikerült lekérni az adatokat az API-ból.")
            return

        vehicles = data.get("vehicles", [])
        for v in vehicles:
            line_id = str(v.get("route_id", "—"))
            if not is_op_line(line_id):
                continue

            reg = v.get("license_plate") or "Ismeretlen"
            dest = v.get("label") or "Ismeretlen"
            lat = v.get("lat")
            lon = v.get("lon")
            trip_id = str(v.get("trip_id") or v.get("vehicle_id") or "")
            vtype = v.get("vehicle_model") or "Ismeretlen"

            if lat is None or lon is None:
                continue

            active[reg] = {
                "line": line_id,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    # Ha nincs aktív jármű
    if not active:
        if last_active != active:
            await channel.send("🚫 Nincs aktív OP vonalon járó jármű.")
            last_active = {}
        return

    # Csak akkor frissítünk, ha van változás
    if active == last_active:
        return
    last_active = active

    # Embed létrehozása
    embeds = []
    embed_title_base = "🚌 Aktív OP vonalon járó járművek"
    embed = discord.Embed(title=embed_title_base, color=0x00ff00)
    field_count = 0

    for reg, info in sorted(active.items()):
        value = (
            f"Vonal: {info['line']}\n"
            f"Cél: {info['dest']}\n"
            f"Típus: {info['type']}\n"
            f"Pozíció: {info['lat']:.5f}, {info['lon']:.5f}"
        )
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x00ff00)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1
    embeds.append(embed)

    # Embed üzenetek küldése / frissítése
    if not embed_messages:
        # Ha még nincs elküldött embed, újakat küldünk
        embed_messages = []
        for e in embeds:
            msg = await channel.send(embed=e)
            embed_messages.append(msg)
    else:
        # Frissítjük a meglévő üzeneteket
        for i, e in enumerate(embeds):
            if i < len(embed_messages):
                try:
                    await embed_messages[i].edit(embed=e)
                except discord.NotFound:
                    # Ha az üzenet törlésre került, újraküldjük
                    msg = await channel.send(embed=e)
                    embed_messages[i] = msg
            else:
                # Ha több embed van, mint korábban, újakat küldünk
                msg = await channel.send(embed=e)
                embed_messages.append(msg)

# Automatikusan indul a bot indításakor
@bot.event
async def on_ready():
    print(f"Bot készen: {bot.user}")
    # Első futtatás azonnal
    await send_op_vehicles()
    # Ezután indul a loop 5 percenként
    if not send_op_vehicles.is_running():
        send_op_vehicles.start()

@bot.command()
async def nosztalgia(ctx):
    active = {}

    # Supabase járművek lekérése aszinkron
    supa_vehicles = await fetch_supabase_vehicles_async()
    
    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue  # nincs rendszám

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

            # 🔥 Mercedes busz szűrés
            if not (is_nosztalgia(reg) or is_obu(reg)):
                continue

            if is_fogas(reg) or is_ics(reg):
                continue

            # 🔥 típus és megjelenítendő rendszám Supabase alapján
            if reg in supa_vehicles:
                vtype = supa_vehicles[reg]["vtype"]
                if is_obu(reg):
                    display_reg = f"{supa_vehicles[reg]['plate']} ({reg})"  # plate + (JARMU)
                else:
                    display_reg = reg
            else:
                # fallback a régi logikára
                if is_nosztalgia(reg):
                    if reg in ["BPI007"]:
                        vtype = "Ikarus 412.10A"
                    elif reg in ["BPI415"]:
                        vtype = "Ikarus 415.14"
                    elif reg in ["BPI829", "BPO477"]:
                        vtype = "Ikarus 280.49"
                    elif reg in ["BPI923"]:
                        vtype = "Ikarus 435.06"
                    elif reg in ["BPO147", "BPO301"]:
                        vtype = "Ikarus 260.46"
                    elif reg in ["BPO449"]:
                        vtype = "Ikarus 280.40A"
                    elif reg in ["AAIK405"]:
                        vtype = "Ikarus 405.06"
                    elif reg in ["V4000", "V4171", "V4200", "V4349"]:
                        vtype = "Tatra T5C5"
                    elif reg in ["T0309"]:
                        vtype = "Ikarus 435.81F"
                    elif reg in ["T0359"]:
                        vtype = "Gräf & Stift J09 NGE152"
                    else:
                        vtype = "Ismeretlen"
                    display_reg = reg
                elif is_obu(reg):
                    vtype = "Egyenlőre ismeretlen OBU jármű"
                    display_reg = f"{reg} ({reg})"  # ha nincs Supabase adat
                else:
                    vtype = "Ismeretlen"
                    display_reg = reg

            active[display_reg] = {
                "line": line_name,
                "dest": dest,
                "trip_id": trip_id,
                "lat": lat,
                "lon": lon,
                "type": vtype
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív nosztalgia jármű.")

    # Embed küldés
    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "Aktív nosztalgia járművek"
    embed = discord.Embed(title=embed_title_base, color=0x00ff00)
    field_count = 0

    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Típus: {i['type']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x00ff00)
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)

@bot.command()
async def bkvkt(ctx):
    vehicles_list = []

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        vehicles = data.get("vehicles", [])
        for v in vehicles:
            dest = v.get("label")
            if dest != "Központi tartalék":
                continue  # csak a Központi tartalék célállomás
            reg = v.get("license_plate") or "Ismeretlen"
            line_id = str(v.get("route_id", "—"))
            line_name = decode_line(line_id)
            lat = v.get("lat")
            lon = v.get("lon")
            model = (v.get("vehicle_model") or "Ismeretlen").lower()

            vehicles_list.append({
                "reg": reg,
                "line": line_name,
                "dest": dest,
                "lat": lat,
                "lon": lon,
                "type": model
            })

    if not vehicles_list:
        return await ctx.send("🚫 Nincs aktívan várakozó Központi Tartalék.")

    # Embed létrehozása
    MAX_FIELDS = 20
    embeds = []
    embed_title_base = "🚍 Járművek - Központi tartalék"
    embed = discord.Embed(title=embed_title_base, color=0x00ff00)
    field_count = 0

    for v in vehicles_list:
        value = (
            f"Vonal: {v['line']}\n"
            f"Cél: {v['dest']}\n"
            f"Típus: {v['type']}\n"
            f"Pozíció: {v['lat']}, {v['lon']}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title=f"{embed_title_base} (folytatás)", color=0x00ff00)
            field_count = 0

        embed.add_field(name=v["reg"], value=value, inline=False)
        field_count += 1

    embeds.append(embed)
    for e in embeds:
        await ctx.send(embed=e)

@bot.command()
async def vehhist(ctx, vehicle: str, date: str = None):
    vehicle = vehicle.upper()  # 🔥 EZ A LÉNYEG

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
        
@bot.command()
async def all(ctx, route_id: str):

    # 🔥 visszaalakítás
    def encode_line(user_input: str) -> str:
        user_input = user_input.upper().strip()

        for k, v in LINE_EXCEPTIONS.items():
            if v.upper() == user_input:
                return k

        if user_input.startswith(("R", "N")):
            prefix = user_input[0]
            num = user_input[1:]
            if num.isdigit():
                return f"{prefix}3{int(num):03d}"

        suffix = "0"
        base = user_input

        if user_input[-1].isalpha():
            base = user_input[:-1]
            for k, v in SUFFIX_MAP.items():
                if v == user_input[-1]:
                    suffix = k
                    break

        if base.isdigit():
            num = int(base)

            if 70 <= num <= 83:  # troli
                return f"4{num:02d}{suffix}"
            elif 1 <= num <= 69:  # villamos
                return f"3{num:02d}{suffix}"
            else:  # busz
                return f"{num:03d}{suffix}"

        return user_input

    real_route_id = encode_line(route_id)

    active = {}

    async with aiohttp.ClientSession() as session:
        data = await fetch_json(session, VEHICLES_API)
        if not data:
            return await ctx.send("❌ Nincs elérhető adat.")

        vehicles = data.get("vehicles", [])

        for v in vehicles:
            reg = v.get("license_plate")
            if not reg:
                continue

            line_id = str(v.get("route_id", ""))
            if line_id != real_route_id:
                continue

            lat = v.get("lat")
            lon = v.get("lon")
            if lat is None or lon is None:
                continue

            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            line_name = decode_line(line_id)
            dest = v.get("label", "Ismeretlen")

            active[reg] = {
                "line": line_name,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send(f"❗ Nincs aktív jármű a *{route_id}* vonalon.")

    MAX_FIELDS = 20
    embeds = []
    embed_title_base = f"🚍 Aktív járművek – {route_id}"
    embed = discord.Embed(title=embed_title_base, color=0x0000ff)
    field_count = 0

    # 🔹 rendszám szerint rendezve
    for reg, i in sorted(active.items(), key=lambda x: x[0]):
        value = (
            f"Vonal: {i['line']}\n"
            f"Cél: {i['dest']}\n"
            f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
        )

        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(
                title=f"{embed_title_base} (folytatás)",
                color=0x0000ff
            )
            field_count = 0

        embed.add_field(name=reg, value=value, inline=False)
        field_count += 1

    embeds.append(embed)

    for e in embeds:
        await ctx.send(embed=e)

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