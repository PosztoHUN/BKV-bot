import asyncio

# ────────────────
# BKV Villamos Today
# ────────────────
@bot.command()
async def bkvvillamostoday(ctx, date: str = None):
    day = resolve_date(date)  # a dátum feldolgozása
    veh_dir = "logs/veh"
    active = {}

    for fname in os.listdir(veh_dir):
        if not fname.endswith(".txt"):
            continue
        reg = fname.replace(".txt","")

        # Ganz troli kizárása
        if is_ganz_troli(reg):
            continue

        # csak villamosok
        if not (is_ganz(reg) or is_tw6000(reg) or is_combino(reg) or 
                is_caf5(reg) or is_caf9(reg) or is_t5c5(reg) or is_oktato(reg)):
            continue

        with open(os.path.join(veh_dir, fname), "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(day):
                    try:
                        ts_str = line.split(" - ")[0]
                        ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                        trip_id = line.split("ID ")[1].split(" ")[0]
                        line_id = line.split("Vonal ")[1].split(" ")[0]
                        line_name = LINE_MAP.get(line_id, line_id)
                        active.setdefault(reg, []).append((ts, line_name, trip_id))
                    except:
                        continue

    if not active:
        return await ctx.send(f"🚫 {day} napon nem közlekedett villamos.")

    # Kiírás szöveges formában (nem embed)
    msg_lines = [f"🚋 Villamosok forgalomban {day}:"]
    for reg in sorted(active):
        first = min(active[reg], key=lambda x: x[0])
        last = max(active[reg], key=lambda x: x[0])
        forgalmi = menetrendi_forgalmi(first[2])
        msg_lines.append(f"{reg} | {first[1]} | {first[0].strftime('%H:%M')} → {last[0].strftime('%H:%M')} | Forgalmi: {forgalmi}")

    # Küldés
    for chunk in [msg_lines[i:i+20] for i in range(0, len(msg_lines), 20)]:
        await ctx.send("\n".join(chunk))
