import discord
from discord.ext import commands, tasks
import os
import json
import time
import aiohttp


# ============================================================
# CẤU HÌNH
# ============================================================

TOKEN = os.getenv("TOKEN")
PREFIX = "?"

POINT_CHANNEL_ID = int(os.getenv("POINT_CHANNEL_ID", "0"))

POINTS_FILE = "points.json"
VOICE_FILE = "voice_time.json"


# ============================================================
# CẤU HÌNH ĐIỂM
# ============================================================

# Cùng Voice đủ 10 phút -> +3 điểm chung
VOICE_POINT_MINUTES = 10
VOICE_POINT_SECONDS = VOICE_POINT_MINUTES * 60
VOICE_POINT_AMOUNT = 3

# Tag nhau -> +1 điểm chung
TAG_POINT_AMOUNT = 1
TAG_COOLDOWN_SECONDS = 5 * 60


# ============================================================
# CẤU HÌNH 100 GIỜ VOICE
# ============================================================

VOICE_REWARD_ROLE_ID = 1543920448503291924
VOICE_REQUIRED_SECONDS = 100 * 60 * 60


# ============================================================
# ROLE ĐƯỢC PHÉP TÍNH ĐIỂM
# ============================================================

ALLOWED_ROLE_IDS = {
    1538841659708547082,
    1539216628980392027,
    1539223863328514160,
    1539223921839046696,
    1539223988646051850,
    1539224042362642432,
    1539224100046635098,
    1539224192531038278,
}


# ============================================================
# INTENTS
# ============================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True


# ============================================================
# BOT
# ============================================================

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)


# ============================================================
# DATABASE
# ============================================================

def load_json(filename):
    if not os.path.exists(filename):
        return {}

    try:
        with open(filename, "r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except Exception as error:
        print(f"[DATABASE] Không đọc được {filename}: {error}")
        return {}


def save_json(filename, data):
    try:
        temp_file = f"{filename}.tmp"

        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=4
            )

        os.replace(temp_file, filename)

    except Exception as error:
        print(f"[DATABASE] Không lưu được {filename}: {error}")


points = load_json(POINTS_FILE)
voice_time = load_json(VOICE_FILE)


# ============================================================
# BỘ NHỚ TẠM THỜI
# ============================================================

tag_cooldowns = {}

# (guild_id, user_id) -> {
#     "channel_id": int,
#     "last_check": float
# }
voice_sessions = {}

# "guild_id:user1-user2" -> số giây cùng Voice
pair_voice_timers = {}

http_session = None


# ============================================================
# HELPER ROLE
# ============================================================

def get_allowed_roles(member):
    return tuple(
        sorted(
            role.id
            for role in member.roles
            if role.id in ALLOWED_ROLE_IDS
        )
    )


def roles_same(member1, member2):
    roles1 = get_allowed_roles(member1)
    roles2 = get_allowed_roles(member2)

    if not roles1 or not roles2:
        return False

    return roles1 == roles2


def get_role_names(member):
    return [
        role.name
        for role in member.roles
        if role.id in ALLOWED_ROLE_IDS
    ]


# ============================================================
# HELPER CẶP
# ============================================================

def get_pair_id(user1, user2):
    ids = sorted((user1.id, user2.id))
    return f"{ids[0]}-{ids[1]}"


def get_pair_points(guild_id, user1, user2):
    guild_data = points.get(str(guild_id), {})
    return guild_data.get(get_pair_id(user1, user2), 0)


# ============================================================
# GIF API
# ============================================================

async def get_anime_gif(reaction):
    global http_session

    url = f"https://api.otakugifs.xyz/gif?reaction={reaction}"

    try:
        if http_session is None or http_session.closed:
            timeout = aiohttp.ClientTimeout(total=8)
            http_session = aiohttp.ClientSession(timeout=timeout)

        async with http_session.get(url) as response:
            if response.status != 200:
                print(f"[GIF] HTTP {response.status}")
                return None

            data = await response.json()
            return data.get("url")

    except Exception as error:
        print(f"[GIF] Lỗi {reaction}: {error}")
        return None


# ============================================================
# THÔNG BÁO ĐIỂM
# ============================================================

async def send_point_notification(user1, user2, amount, reason, total):
    if POINT_CHANNEL_ID == 0:
        return

    channel = user1.guild.get_channel(POINT_CHANNEL_ID)

    if channel is None:
        print(f"[POINT] Không tìm thấy kênh {POINT_CHANNEL_ID}")
        return

    role_names = get_role_names(user1)
    role_text = ", ".join(role_names) if role_names else "Không xác định"

    try:
        await channel.send(
            f"💖 **CẶP ĐƯỢC CỘNG ĐIỂM!**\n"
            f"👤 {user1.mention} ❤️ {user2.mention}\n"
            f"🎭 Role: `{role_text}`\n"
            f"➕ **+{amount} điểm**\n"
            f"🏆 Điểm chung: **{total}**\n"
            f"📌 {reason}"
        )

    except discord.Forbidden:
        print("[POINT] Bot không có quyền gửi tin nhắn.")

    except Exception as error:
        print(f"[POINT] Lỗi gửi thông báo: {error}")


# ============================================================
# CỘNG ĐIỂM CHUNG
# ============================================================

async def add_pair_point(user1, user2, amount, reason):
    if not roles_same(user1, user2):
        return False

    guild_id = str(user1.guild.id)
    pair_id = get_pair_id(user1, user2)

    if guild_id not in points:
        points[guild_id] = {}

    points[guild_id][pair_id] = (
        points[guild_id].get(pair_id, 0) + amount
    )

    save_json(POINTS_FILE, points)

    total = points[guild_id][pair_id]

    print(
        f"[POINT] {user1.display_name} + "
        f"{user2.display_name} -> +{amount} = {total}"
    )

    await send_point_notification(
        user1,
        user2,
        amount,
        reason,
        total
    )

    return True


# ============================================================
# VOICE DATA
# ============================================================

def get_voice_data(guild_id, user_id):
    guild_id = str(guild_id)
    user_id = str(user_id)

    if guild_id not in voice_time:
        voice_time[guild_id] = {}

    if user_id not in voice_time[guild_id]:
        voice_time[guild_id][user_id] = {
            "continuous_seconds": 0,
            "reward": False
        }

    data = voice_time[guild_id][user_id]

    if not isinstance(data, dict):
        data = {
            "continuous_seconds": 0,
            "reward": False
        }
        voice_time[guild_id][user_id] = data

    data.setdefault("continuous_seconds", 0)
    data.setdefault("reward", False)

    return data


def reset_continuous_voice(guild_id, user_id):
    data = get_voice_data(guild_id, user_id)

    # Chỉ reset chuỗi thời gian.
    # reward vẫn giữ nguyên để role 100 giờ chỉ được ghi nhận một lần.
    data["continuous_seconds"] = 0

    save_json(VOICE_FILE, voice_time)

    print(f"[VOICE] Reset chuỗi: {user_id}")


# ============================================================
# CẤP ROLE 100 GIỜ
# ============================================================

async def give_voice_reward(member):
    guild_id = str(member.guild.id)
    user_id = str(member.id)

    data = get_voice_data(guild_id, user_id)

    if data.get("reward", False):
        return

    role = member.guild.get_role(VOICE_REWARD_ROLE_ID)

    if role is None:
        print(
            f"[REWARD] Không tìm thấy role "
            f"{VOICE_REWARD_ROLE_ID}"
        )
        return

    try:
        if role not in member.roles:
            await member.add_roles(
                role,
                reason="Đạt 100 giờ Voice liên tục"
            )

        data["reward"] = True
        save_json(VOICE_FILE, voice_time)

        print(f"[REWARD] {member} đã đạt 100 giờ Voice.")

        if POINT_CHANNEL_ID != 0:
            channel = member.guild.get_channel(POINT_CHANNEL_ID)

            if channel is not None:
                await channel.send(
                    f"🏆 **CHÚC MỪNG!**\n"
                    f"🎧 {member.mention}\n"
                    f"⏱️ Đã đạt **100 giờ Voice LIÊN TỤC**!\n"
                    f"🎖️ Đã nhận role {role.mention}"
                )

    except discord.Forbidden:
        print(
            "[REWARD] Bot không có quyền cấp role. "
            "Hãy đặt role của bot cao hơn role phần thưởng."
        )

    except Exception as error:
        print(f"[REWARD] Lỗi: {error}")


# ============================================================
# CỘNG THỜI GIAN VOICE
# ============================================================

async def update_voice_time(member, seconds):
    data = get_voice_data(
        member.guild.id,
        member.id
    )

    if data.get("reward", False):
        return

    data["continuous_seconds"] += max(0, int(seconds))

    save_json(VOICE_FILE, voice_time)

    if data["continuous_seconds"] >= VOICE_REQUIRED_SECONDS:
        await give_voice_reward(member)


# ============================================================
# VOICE TRACKER
# ============================================================

@tasks.loop(seconds=60)
async def voice_tracker():
    now = time.time()

    for guild in bot.guilds:
        current_users = set()

        # ----------------------------------------------------
        # Tạo danh sách người đang ở Voice
        # ----------------------------------------------------
        for member in guild.members:
            if member.bot:
                continue

            if member.voice is None:
                continue

            if member.voice.channel is None:
                continue

            current_users.add(member.id)

            key = (guild.id, member.id)
            channel_id = member.voice.channel.id

            # Mới vào Voice
            if key not in voice_sessions:
                voice_sessions[key] = {
                    "channel_id": channel_id,
                    "last_check": now
                }
                continue

            session = voice_sessions[key]

            # Đổi phòng -> reset chuỗi
            if session["channel_id"] != channel_id:
                session["channel_id"] = channel_id
                session["last_check"] = now

                reset_continuous_voice(
                    guild.id,
                    member.id
                )

        # ----------------------------------------------------
        # Người đã rời Voice
        # ----------------------------------------------------
        for key in list(voice_sessions.keys()):
            key_guild_id, user_id = key

            if key_guild_id != guild.id:
                continue

            if user_id not in current_users:
                del voice_sessions[key]

                reset_continuous_voice(
                    guild.id,
                    user_id
                )

        # ----------------------------------------------------
        # Cộng thời gian Voice
        # ----------------------------------------------------
        for key in list(voice_sessions.keys()):
            key_guild_id, user_id = key

            if key_guild_id != guild.id:
                continue

            member = guild.get_member(user_id)

            if member is None:
                continue

            if member.voice is None or member.voice.channel is None:
                continue

            session = voice_sessions[key]

            elapsed = int(now - session["last_check"])

            if elapsed <= 0:
                continue

            session["last_check"] = now

            await update_voice_time(
                member,
                elapsed
            )

        # ----------------------------------------------------
        # Gom người theo từng phòng Voice
        # ----------------------------------------------------
        rooms = {}

        for member in guild.members:
            if member.bot:
                continue

            if member.voice is None or member.voice.channel is None:
                continue

            channel_id = member.voice.channel.id
            rooms.setdefault(channel_id, []).append(member)

        # ----------------------------------------------------
        # Tính điểm cặp cùng Voice
        # ----------------------------------------------------
        active_pairs = set()

        for members in rooms.values():
            if len(members) < 2:
                continue

            for index in range(len(members)):
                for other_index in range(index + 1, len(members)):
                    user1 = members[index]
                    user2 = members[other_index]

                    if not roles_same(user1, user2):
                        continue

                    pair_id = get_pair_id(user1, user2)
                    pair_key = f"{guild.id}:{pair_id}"

                    active_pairs.add(pair_key)
                    pair_voice_timers[pair_key] = (
                        pair_voice_timers.get(pair_key, 0) + 60
                    )

                    if pair_voice_timers[pair_key] >= VOICE_POINT_SECONDS:
                        pair_voice_timers[pair_key] -= VOICE_POINT_SECONDS

                        await add_pair_point(
                            user1,
                            user2,
                            VOICE_POINT_AMOUNT,
                            (
                                f"🎧 Cùng Voice đủ "
                                f"{VOICE_POINT_MINUTES} phút."
                            )
                        )

        # ----------------------------------------------------
        # Xóa timer của cặp không còn cùng phòng
        # ----------------------------------------------------
        guild_prefix = f"{guild.id}:"

        for pair_key in list(pair_voice_timers.keys()):
            if pair_key.startswith(guild_prefix):
                if pair_key not in active_pairs:
                    del pair_voice_timers[pair_key]


# ============================================================
# MESSAGE EVENT - TAG
# ============================================================

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.guild is None:
        await bot.process_commands(message)
        return

    author = message.author

    for target in message.mentions:
        if target.bot:
            continue

        if target.id == author.id:
            continue

        if not roles_same(author, target):
            continue

        pair_id = get_pair_id(author, target)
        cooldown_key = f"{message.guild.id}:{pair_id}"

        now = time.time()
        last_tag = tag_cooldowns.get(cooldown_key, 0)

        if now - last_tag < TAG_COOLDOWN_SECONDS:
            continue

        tag_cooldowns[cooldown_key] = now

        await add_pair_point(
            author,
            target,
            TAG_POINT_AMOUNT,
            "🏷️ Tag nhau."
        )

    await bot.process_commands(message)


# ============================================================
# LỆNH TƯƠNG TÁC
# ============================================================

async def send_interaction(
    ctx,
    member,
    reaction,
    emoji,
    action,
    color
):
    if member is None:
        await ctx.send(
            f"❌ Dùng: `{PREFIX}{ctx.command.name} @user`"
        )
        return

    if member.id == ctx.author.id:
        await ctx.send(
            f"{emoji} **{ctx.author.display_name}** {action} chính mình."
        )
        return

    gif_url = await get_anime_gif(reaction)

    embed = discord.Embed(
        description=(
            f"{emoji} **{ctx.author.display_name}** "
            f"{action} **{member.display_name}**!"
        ),
        color=color
    )

    if gif_url:
        embed.set_image(url=gif_url)

    await ctx.send(embed=embed)


@bot.command(name="om", aliases=["hug"])
async def om(ctx, member: discord.Member = None):
    await send_interaction(
        ctx,
        member,
        "hug",
        "🤗",
        "đã ôm",
        discord.Color.pink()
    )


@bot.command(name="hon", aliases=["kiss"])
async def hon(ctx, member: discord.Member = None):
    await send_interaction(
        ctx,
        member,
        "kiss",
        "💋",
        "đã hôn",
        discord.Color.red()
    )


@bot.command(name="xoadau", aliases=["pat"])
async def xoadau(ctx, member: discord.Member = None):
    await send_interaction(
        ctx,
        member,
        "pat",
        "🫳",
        "đã xoa đầu",
        discord.Color.light_grey()
    )


@bot.command(name="thomma", aliases=["cheek"])
async def thomma(ctx, member: discord.Member = None):
    await send_interaction(
        ctx,
        member,
        "kiss",
        "😚",
        "đã thơm má",
        discord.Color.purple()
    )


@bot.command(name="canyeu", aliases=["bite"])
async def canyeu(ctx, member: discord.Member = None):
    await send_interaction(
        ctx,
        member,
        "bite",
        "🦷",
        "đã cắn yêu",
        discord.Color.orange()
    )


# ============================================================
# ?DIEM
# ============================================================

@bot.command(name="diem")
async def diem(ctx, member: discord.Member = None):
    if member is None:
        await ctx.send("❌ Dùng: `?diem @user`")
        return

    if member.bot:
        await ctx.send("❌ Không thể xem điểm với bot.")
        return

    if not roles_same(ctx.author, member):
        await ctx.send(
            "❌ Hai người không có bộ role giống nhau."
        )
        return

    score = get_pair_points(
        ctx.guild.id,
        ctx.author,
        member
    )

    await ctx.send(
        f"💖 **ĐIỂM CHUNG**\n\n"
        f"👤 {ctx.author.mention}\n"
        f"❤️ {member.mention}\n\n"
        f"🏆 **{score} điểm**"
    )


# ============================================================
# ?GIO
# ============================================================

@bot.command(name="gio")
async def gio(ctx):
    data = get_voice_data(
        ctx.guild.id,
        ctx.author.id
    )

    seconds = int(data.get("continuous_seconds", 0))
    hours = seconds / 3600

    remaining = max(
        0,
        VOICE_REQUIRED_SECONDS - seconds
    )

    remaining_hours = remaining / 3600

    if data.get("reward", False):
        status = "🏆 Đã nhận role 100 giờ."
    else:
        status = "⏳ Chưa đạt 100 giờ."

    await ctx.send(
        f"🎧 **VOICE LIÊN TỤC**\n\n"
        f"👤 {ctx.author.mention}\n"
        f"⏱️ Đã Voice: **{hours:.2f} giờ**\n"
        f"🏆 Mục tiêu: **100 giờ**\n"
        f"⌛ Còn lại: **{remaining_hours:.2f} giờ**\n"
        f"📌 {status}\n\n"
        f"⚠️ Rời Voice hoặc đổi phòng sẽ reset "
        f"thời gian liên tục về 0."
    )


# ============================================================
# ?TOP
# ============================================================

@bot.command(name="top")
async def top(ctx):
    guild_id = str(ctx.guild.id)
    data = points.get(guild_id, {})

    if not data:
        await ctx.send("📊 Chưa có cặp nào có điểm.")
        return

    ranking = sorted(
        data.items(),
        key=lambda item: item[1],
        reverse=True
    )[:10]

    lines = [
        "🏆 **TOP CẶP ĐIỂM**",
        ""
    ]

    count = 0

    for pair_id, score in ranking:
        try:
            id1, id2 = pair_id.split("-", 1)

            member1 = ctx.guild.get_member(int(id1))
            member2 = ctx.guild.get_member(int(id2))

            name1 = (
                member1.display_name
                if member1
                else f"User {id1}"
            )

            name2 = (
                member2.display_name
                if member2
                else f"User {id2}"
            )

            count += 1

            lines.append(
                f"**{count}.** {name1} ❤️ {name2} "
                f"— **{score} điểm**"
            )

        except (ValueError, TypeError):
            continue

    if count == 0:
        await ctx.send("📊 Không có dữ liệu cặp hợp lệ.")
        return

    await ctx.send("\n".join(lines))


# ============================================================
# ?RESETDIEM
# ============================================================

@bot.command(name="resetdiem")
@commands.has_permissions(administrator=True)
async def resetdiem(ctx):
    guild_id = str(ctx.guild.id)

    points[guild_id] = {}

    save_json(
        POINTS_FILE,
        points
    )

    await ctx.send(
        "🗑️ **Đã reset toàn bộ điểm chung.**"
    )


# ============================================================
# ?HELP
# ============================================================

@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="🤖 DANH SÁCH LỆNH",
        description="Prefix: `?`",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="💖 Tương tác",
        value=(
            "`?om @user` / `?hug @user`\n"
            "`?hon @user` / `?kiss @user`\n"
            "`?xoadau @user` / `?pat @user`\n"
            "`?thomma @user` / `?cheek @user`\n"
            "`?canyeu @user` / `?bite @user`"
        ),
        inline=False
    )

    embed.add_field(
        name="🏆 Điểm",
        value=(
            "`?diem @user` — Xem điểm chung\n"
            "`?top` — Xem TOP 10 cặp\n"
            "`?resetdiem` — Reset điểm (Admin)"
        ),
        inline=False
    )

    embed.add_field(
        name="🎧 Voice",
        value=(
            "`?gio` — Xem Voice liên tục\n\n"
            "🎧 Cùng Voice 10 phút → **+3 điểm chung**\n"
            "🏷️ Tag → **+1 điểm chung / 5 phút**\n"
            "🏆 100 giờ Voice liên tục → **cấp role**"
        ),
        inline=False
    )

    await ctx.send(embed=embed)


# ============================================================
# COMMAND ERROR
# ============================================================

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return

    if isinstance(error, commands.MissingPermissions):
        await ctx.send(
            "❌ Bạn không có quyền dùng lệnh này."
        )
        return

    if isinstance(error, commands.MemberNotFound):
        await ctx.send(
            "❌ Không tìm thấy người dùng."
        )
        return

    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            "❌ Bạn chưa nhập đủ tham số."
        )
        return

    if isinstance(error, commands.BadArgument):
        await ctx.send(
            "❌ Tham số không hợp lệ. Hãy tag đúng người dùng."
        )
        return

    print(f"[COMMAND ERROR] {error}")


# ============================================================
# READY
# ============================================================

@bot.event
async def on_ready():
    print("=" * 60)
    print(f"BOT ONLINE: {bot.user}")
    print(f"BOT ID: {bot.user.id}")
    print(f"SERVER COUNT: {len(bot.guilds)}")
    print(f"PREFIX: {PREFIX}")
    print(
        f"VOICE POINT: {VOICE_POINT_MINUTES} phút "
        f"= +{VOICE_POINT_AMOUNT} điểm"
    )
    print("TAG POINT: +1 / 5 phút / cặp")
    print("VOICE REWARD: 100 giờ liên tục")
    print(f"REWARD ROLE: {VOICE_REWARD_ROLE_ID}")
    print("=" * 60)

    if not voice_tracker.is_running():
        voice_tracker.start()
        print("VOICE TRACKER STARTED")


# ============================================================
# SHUTDOWN
# ============================================================

@bot.event
async def on_close():
    global http_session

    if http_session is not None:
        try:
            await http_session.close()
        except Exception:
            pass

        http_session = None


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "TOKEN chưa được đặt trong Railway Variables."
        )

    bot.run(TOKEN)
