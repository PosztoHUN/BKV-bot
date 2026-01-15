import discord
from discord.ext import commands, tasks
import aiohttp
import os
import sys
from datetime import datetime, timedelta 

# =======================
# BEÁLLÍTÁSOK
# =======================

TOKEN = os.getenv("TOKEN")

API_BASE = "https://bkv-realtime-map.onrender.com"

STOP_API = f"{API_BASE}/stop?stopId={{stop_id}}"
VEHICLES_API = f"{API_BASE}/vehicles"

# WATCH_STOPS = {
#     "166","289","346","391","725","792","1008","1112","1247","1333",
#     "1346","1800","1935","1994","2185","2225","2228","2360","2391",
#     "2432","2502","2503","2544","2549","2587","2588","2900","2901",
#     "2902","1989"
# }

TRAM_LINES = {"3010", "3011", "3020", "3022", "3030", "3040", "3060", "3120", "3140", "3170", "3190", "3230", "3240", "3280", "3281", "3370", "3371", "3420", "3500", "3510", "3511", "3520", "3560", "3561", "3590", "3591", "3592", "3600", "3610", "3620", "3621", "3690", " ", "-", "9999"}

LOCK_FILE = "/tmp/discord_bot.lock"

if os.path.exists(LOCK_FILE):
    print("A bot már fut, kilépés.")
    sys.exit(0)


# =======================
# DISCORD INIT
# =======================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=".", intents=intents)

# =======================
# SEGÉDFÜGGVÉNYEK
# =======================

def in_bbox(lat, lon):
    return (
        47.35 <= lat <= 47.60 and
        18.90 <= lon <= 19.30
    )


def ensure_dirs():
    os.makedirs("logs", exist_ok=True)
    os.makedirs("logs/veh", exist_ok=True)
    
NOSZTALGIA = {"V313", "V314", "V313-V314", "V813"}

def is_nos(reg):
    if not isinstance(reg, str):
        return False
    if reg.startswith("V") and reg[1:].isdigit():
        n = int(reg[1:])
        if 12 <= n <= 12:
            return True
    return reg in NOSZTALGIA
    


def is_tw6000(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("V"):
        return False
    if not reg[1:].isdigit():
        return False
    return 1500 <= int(reg[1:]) <= 1624 

def is_t5c5(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("V"):
        return False
    if not reg[1:].isdigit():
        return False
    return 4000 <= int(reg[1:]) <= 4349 

def is_ganz(reg):
    if not isinstance(reg, str):
        return False
    if not reg.startswith("V"):
        return False
    if reg[1:].isdigit():
        n = int(reg[1:])
        if 1301 <= n <= 1499:
            return True

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

def save_trip(dep_id, line, vehicle, dest):
    ensure_dirs()
    today = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    trip_dir = f"logs/{today}"
    os.makedirs(trip_dir, exist_ok=True)

    trip_file = f"{trip_dir}/{dep_id}.txt"
    if not os.path.exists(trip_file):
        with open(trip_file, "w", encoding="utf-8") as f:
            f.write(
                f"Dátum: {today}\n"
                f"ID: {dep_id}\n"
                f"Vonal: {line}\n"
                f"Cél: {dest}\n"
                f"Jármű: {vehicle}\n"
                f"Első észlelés: {ts}\n"
            )

    veh_file = f"logs/veh/{vehicle}.txt"
    last_id = None

    if os.path.exists(veh_file):
        with open(veh_file, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
            if lines and "ID " in lines[-1]:
                last_id = lines[-1].split("ID ")[1].split(" ")[0]

    if last_id != dep_id:
        with open(veh_file, "a", encoding="utf-8") as f:
            f.write(f"{ts} - ID {dep_id} - Vonal {line} - {dest}\n")

def resolve_date(date_arg):
    today = datetime.now().date()
    if date_arg is None:
        return today.strftime("%Y-%m-%d")
    if date_arg.endswith("d"):
        d = int(date_arg[:-1])
        return (today - timedelta(days=d)).strftime("%Y-%m-%d")
    return date_arg

# =======================
# LOGGER LOOP
# =======================

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

# @bot.command()
# async def bkvvillamos(ctx):
#     active = {}  # <-- IDE KELL IDEGENÍTENI

#     # például: lekérdezés az API-ból
#     async with aiohttp.ClientSession() as session:
#         vehicles = await fetch_json(session, VEHICLES_API)
#         if not isinstance(vehicles, list):
#             return await ctx.send("❌ Nincs elérhető adat.")

#         for v in vehicles:
#             reg = v.get("license_plate")
#             line = v.get("route_id", "—")
#             dest = v.get("destination", "Ismeretlen")

#             if not reg:
#                 continue

#             active[reg] = {"line": line, "dest": dest}

#     # embed küldés
#     MAX_FIELDS = 20
#     embeds = []
#     embed = discord.Embed(title="🚋 Aktív villamosok", color=0xffff00)
#     field_count = 0

#     for reg, i in active.items():
#         if field_count >= MAX_FIELDS:
#             embeds.append(embed)
#             embed = discord.Embed(title="🚋 Aktív villamosok (folyt.)", color=0xffff00)
#             field_count = 0

#         embed.add_field(
#             name=reg,
#             value=f"Vonal: {i['line']}\nCél: {i['dest']}",
#             inline=False
#         )
#         field_count += 1

#     embeds.append(embed)
#     for e in embeds:
#         await ctx.send(embed=e)

    
@bot.command()
async def bkvganz(ctx):
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
            line = str(v.get("route_id", "—"))

            if not reg or lat is None or lon is None:
                continue

            # csak Ganz
            if "ganz" not in model:
                continue

            # Budapest (biztos tartomány)
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {
                "line": line,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Ganz villamos.")

    embed = discord.Embed(title="🚋 Aktív Ganz villamosok", color=0xffff00)
    for reg, i in active.items():
        embed.add_field(
            name=reg,
            value=(
                f"Vonal (ID): {i['line']}\n"
                f"Cél: {i['dest']}\n"
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )

    await ctx.send(embed=embed)

    
@bot.command()
async def bkvtw6000(ctx):
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
            line = str(v.get("route_id", "—"))

            if not reg or lat is None or lon is None:
                continue

            # TW6000 azonosítás rendszám alapján
            if not is_tw6000(reg):
                continue

            # Budapest környéke (biztos tartomány)
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {
                "line": line,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív TW6000-es villamos.")

    embed = discord.Embed(title="🚋 Aktív TW6000-es villamosok", color=0xffff00)
    for reg, i in active.items():
        embed.add_field(
            name=reg,
            value=(
                f"Vonal (ID): {i['line']}\n"
                f"Cél: {i['dest']}\n"
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )

    await ctx.send(embed=embed)

    
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
            line = str(v.get("route_id", "—"))

            if not reg or lat is None or lon is None:
                continue

            # Combino felismerés rendszám alapján
            if not is_combino(reg):
                continue

            # Budapest környéke
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {
                "line": line,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Combino villamos.")

    embed = discord.Embed(title="🚋 Aktív Combino villamosok", color=0xffff00)
    for reg, i in active.items():
        embed.add_field(
            name=reg,
            value=(
                f"Vonal (ID): {i['line']}\n"
                f"Cél: {i['dest']}\n"
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )

    await ctx.send(embed=embed)

    
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
            line = str(v.get("route_id", "—"))

            if not reg or lat is None or lon is None:
                continue

            # CAF5 felismerés rendszám alapján
            if not is_caf5(reg):
                continue

            # Budapest környéke
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {
                "line": line,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív CAF5 villamos.")

    embed = discord.Embed(title="🚋 Aktív CAF5 villamosok", color=0xffff00)
    for reg, i in active.items():
        embed.add_field(
            name=reg,
            value=(
                f"Vonal (ID): {i['line']}\n"
                f"Cél: {i['dest']}\n"
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )

    await ctx.send(embed=embed)

    
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
            line = str(v.get("route_id", "—"))

            if not reg or lat is None or lon is None:
                continue

            # CAF9 felismerés
            if not is_caf9(reg):
                continue

            # Budapest környéke
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {
                "line": line,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív CAF9 villamos.")

    embed = discord.Embed(title="🚋 Aktív CAF9 villamosok", color=0xffff00)
    for reg, i in active.items():
        embed.add_field(
            name=reg,
            value=(
                f"Vonal (ID): {i['line']}\n"
                f"Cél: {i['dest']}\n"
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )

    await ctx.send(embed=embed)

@bot.command()
async def bkvtatra(ctx):
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
            line = str(v.get("route_id", "—"))

            if not reg or lat is None or lon is None:
                continue

            # Tatra (T5C5)
            if not is_t5c5(reg):
                continue

            # Budapest környéke
            if not (47.20 <= lat <= 47.75 and 18.80 <= lon <= 19.60):
                continue

            active[reg] = {
                "line": line,
                "dest": dest,
                "lat": lat,
                "lon": lon
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív Tatra villamos.")

    embed = discord.Embed(title="🚋 Aktív Tatra villamosok", color=0xffff00)
    for reg, i in active.items():
        embed.add_field(
            name=reg,
            value=(
                f"Vonal (ID): {i['line']}\n"
                f"Cél: {i['dest']}\n"
                f"Pozíció: {i['lat']:.5f}, {i['lon']:.5f}"
            ),
            inline=False
        )

    await ctx.send(embed=embed)



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

@bot.command()
async def bkvganztoday(ctx, date: str = None):
    day = resolve_date(date)
    veh_dir = "logs/veh"
    skodas = {}

    for fname in os.listdir(veh_dir):
        if not fname.endswith(".txt"):
            continue
        reg = fname.replace(".txt","")
        if not is_ganz(reg):
            continue

        with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(day):
                    ts = line.split(" - ")[0]
                    trip_id = line.split("ID ")[1].split(" ")[0]
                    line_no = line.split("Vonal ")[1].split(" ")[0]
                    skodas.setdefault(reg, []).append((ts, line_no, trip_id))

    if not skodas:
        return await ctx.send(f"🚫 {day} napon nem közlekedett Ganz.")

    out = [f"🚊 Ganz – forgalomban ({day})"]
    for reg in sorted(skodas):
        first = min(skodas[reg], key=lambda x: x[0])
        last = max(skodas[reg], key=lambda x: x[0])
        out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

    msg = "\n".join(out)
    for i in range(0, len(msg), 1900):
        await ctx.send(msg[i:i+1900])

@bot.command()
async def bkvtw6000today(ctx, date: str = None):
    day = resolve_date(date)
    veh_dir = "logs/veh"
    skodas = {}

    for fname in os.listdir(veh_dir):
        if not fname.endswith(".txt"):
            continue
        reg = fname.replace(".txt","")
        if not is_tw6000(reg):
            continue

        with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(day):
                    ts = line.split(" - ")[0]
                    trip_id = line.split("ID ")[1].split(" ")[0]
                    line_no = line.split("Vonal ")[1].split(" ")[0]
                    skodas.setdefault(reg, []).append((ts, line_no, trip_id))

    if not skodas:
        return await ctx.send(f"🚫 {day} napon nem közlekedett TW6000.")

    out = [f"🚊 TW6000 – forgalomban ({day})"]
    for reg in sorted(skodas):
        first = min(skodas[reg], key=lambda x: x[0])
        last = max(skodas[reg], key=lambda x: x[0])
        out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

    msg = "\n".join(out)
    for i in range(0, len(msg), 1900):
        await ctx.send(msg[i:i+1900])

@bot.command()
async def bkvcombinotoday(ctx, date: str = None):
    day = resolve_date(date)
    veh_dir = "logs/veh"
    skodas = {}

    for fname in os.listdir(veh_dir):
        if not fname.endswith(".txt"):
            continue
        reg = fname.replace(".txt","")
        if not is_combino(reg):
            continue

        with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(day):
                    ts = line.split(" - ")[0]
                    trip_id = line.split("ID ")[1].split(" ")[0]
                    line_no = line.split("Vonal ")[1].split(" ")[0]
                    skodas.setdefault(reg, []).append((ts, line_no, trip_id))

    if not skodas:
        return await ctx.send(f"🚫 {day} napon nem közlekedett Combino.")

    out = [f"🚊 Combino – forgalomban ({day})"]
    for reg in sorted(skodas):
        first = min(skodas[reg], key=lambda x: x[0])
        last = max(skodas[reg], key=lambda x: x[0])
        out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

    msg = "\n".join(out)
    for i in range(0, len(msg), 1900):
        await ctx.send(msg[i:i+1900])        

@bot.command()
async def bkvcaftoday(ctx, date: str = None):
    day = resolve_date(date)
    veh_dir = "logs/veh"
    skodas = {}

    for fname in os.listdir(veh_dir):
        if not fname.endswith(".txt"):
            continue
        reg = fname.replace(".txt","")
        if not is_caf5(reg)  and not is_caf9(reg):
            continue

        with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(day):
                    ts = line.split(" - ")[0]
                    trip_id = line.split("ID ")[1].split(" ")[0]
                    line_no = line.split("Vonal ")[1].split(" ")[0]
                    skodas.setdefault(reg, []).append((ts, line_no, trip_id))

    if not skodas:
        return await ctx.send(f"🚫 {day} napon nem közlekedett CAF.")

    out = [f"🚊 CAF – forgalomban ({day})"]
    for reg in sorted(skodas):
        first = min(skodas[reg], key=lambda x: x[0])
        last = max(skodas[reg], key=lambda x: x[0])
        out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

    msg = "\n".join(out)
    for i in range(0, len(msg), 1900):
        await ctx.send(msg[i:i+1900])      
        
@bot.command()
async def bkvtatratoday(ctx, date: str = None):
    day = resolve_date(date)
    veh_dir = "logs/veh"
    skodas = {}

    for fname in os.listdir(veh_dir):
        if not fname.endswith(".txt"):
            continue
        reg = fname.replace(".txt","")
        if not is_t5c5(reg):
            continue

        with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(day):
                    ts = line.split(" - ")[0]
                    trip_id = line.split("ID ")[1].split(" ")[0]
                    line_no = line.split("Vonal ")[1].split(" ")[0]
                    skodas.setdefault(reg, []).append((ts, line_no, trip_id))

    if not skodas:
        return await ctx.send(f"🚫 {day} napon nem közlekedett Tatra.")

    out = [f"🚊 Tatra – forgalomban ({day})"]
    for reg in sorted(skodas):
        first = min(skodas[reg], key=lambda x: x[0])
        last = max(skodas[reg], key=lambda x: x[0])
        out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

    msg = "\n".join(out)
    for i in range(0, len(msg), 1900):
        await ctx.send(msg[i:i+1900])  
@bot.command()
async def vehicleinfo(ctx, vehicle: str):
    path = f"logs/veh/{vehicle}.txt"
    if not os.path.exists(path):
        return await ctx.send(f"❌ Nincs adat a(z) {vehicle} járműről.")

    with open(path, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]

    last = lines[-1]
    await ctx.send(f"🚊 **{vehicle} utolsó menete**\n```{last}```")
    
@bot.command()
async def bkvtanulotoday(ctx, date: str = None):
    day = resolve_date(date)
    veh_dir = "logs/veh"
    skodas = {}

    for fname in os.listdir(veh_dir):
        if not fname.endswith(".txt"):
            continue
        reg = fname.replace(".txt","")
        if not is_oktato(reg):
            continue

        with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(day):
                    ts = line.split(" - ")[0]
                    trip_id = line.split("ID ")[1].split(" ")[0]
                    line_no = line.split("Vonal ")[1].split(" ")[0]
                    skodas.setdefault(reg, []).append((ts, line_no, trip_id))

    if not skodas:
        return await ctx.send(f"🚫 {day} napon nem közlekedett CAF.")

    out = [f"🚊 CAF – forgalomban ({day})"]
    for reg in sorted(skodas):
        first = min(skodas[reg], key=lambda x: x[0])
        last = max(skodas[reg], key=lambda x: x[0])
        out.append(f"{reg} — {first[0][11:16]} → {last[0][11:16]} (vonal {first[1]})")

    msg = "\n".join(out)
    for i in range(0, len(msg), 1900):
        await ctx.send(msg[i:i+1900])  

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