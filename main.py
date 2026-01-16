@bot.command()
async def bkvvillamos(ctx):
    active = {}

    async with aiohttp.ClientSession() as session:
        vehicles = await fetch_json(session, VEHICLES_API)
        if not isinstance(vehicles, list):
            return await ctx.send("❌ Nincs elérhető adat az API-ból.")

        for v in vehicles:
            reg = v.get("license_plate")
            line = str(v.get("route_id", "—"))
            dest = v.get("destination", "Ismeretlen")
            fleet = v.get("fleet_number", "?")  # forgalmi szám

            if not reg:
                continue

            # Mentés az active dict-be
            active[reg] = {
                "line": line,
                "dest": dest,
                "fleet": fleet
            }

    if not active:
        return await ctx.send("🚫 Nincs aktív villamos az API szerint.")

    # ===== EMBED DARABOLÁS =====
    MAX_FIELDS = 20
    embeds = []

    embed = discord.Embed(title="🚋 Aktív villamosok", color=0xffff00)
    field_count = 0

    for reg, i in sorted(active.items()):
        if field_count >= MAX_FIELDS:
            embeds.append(embed)
            embed = discord.Embed(title="🚋 Aktív villamosok (folytatás)", color=0xffff00)
            field_count = 0

        embed.add_field(
            name=f"{i['fleet']}",  # forgalmi szám a címben
            value=f"Vonal: {i['line']}\nCél: {i['dest']}",
            inline=False
        )
        field_count += 1

    embeds.append(embed)

    for e in embeds:
        await ctx.send(embed=e)
