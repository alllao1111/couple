import discord
from discord.ext import commands, tasks
import os
import json
import time
import aiohttp


# ============================================================
# CONFIG
# ============================================================

TOKEN = os.getenv("TOKEN")
PREFIX = "?"

# Kênh thông báo điểm
POINT_CHANNEL_ID = int(os.getenv("POINT_CHANNEL_ID", "0"))

# File dữ liệu
POINTS_FILE = "points.json"
VOICE_FILE = "voice_time.json"


# ============================================================
# POINT CONFIG
# ============================================================

# Cùng một Voice đủ 10 phút
# => +3 điểm chung
VOICE_POINT_MINUTES = 10
VOICE_POINT_SECONDS = VOICE_POINT_MINUTES * 60
VOICE_POINT_AMOUNT = 3

# Tag nhau
# => +1 điểm chung
TAG_POINT_AMOUNT = 1

# Cooldown tag
# 5 phút / cặp
TAG_COOLDOWN_SECONDS = 5 * 60


# ============================================================
# 100 HOURS VOICE CONFIG
# ============================================================

# Role được cấp khi đạt 100 giờ Voice liên tục
VOICE_REWARD_ROLE_ID = 1543920448503291924

# 100 giờ
VOICE_REQUIRED_SECONDS = 100 * 60 * 60


# ============================================================
# ALLOWED ROLES
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
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict):
            return data

        return {}

    except Exception as e:
        print(f"ERROR loading {filename}: {e}")
        return {}


def save_json(filename, data):
    try:
        temp_filename = filename + ".tmp"

        with open(temp_filename, "w", encoding="utf-8") as f:
            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=4
            )

        os.replace(temp_filename, filename)

    except Exception as e:
        print(f"ERROR saving {filename}: {e}")


points = load_json(POINTS_FILE)
voice_time = load_json(VOICE_FILE)


# ============================================================
# MEMORY
# ============================================================

# Tag cooldown
# key:
# guild_id:user1-user2
tag_cooldowns = {}


# Người đang ở Voice
#
# key:
# (guild_id, user_id)
#
# value:
# {
#     "channel_id": channel_id,
#     "last_check": timestamp
# }
voice_sessions = {}


# Thời gian 2 người cùng Voice
#
# key:
# guild_id:user1-user2
#
# value:
# số giây
pair_voice_timers = {}


# HTTP session cho GIF
http_session = None


# ============================================================
# ROLE FUNCTIONS
# ============================================================

def get_allowed_roles(member):
    """
    Chỉ lấy những role nằm trong ALLOWED_ROLE_IDS.
    """

    return tuple(
        sorted(
            role.id
            for role in member.roles
            if role.id in ALLOWED_ROLE_IDS
        )
    )


def roles_same(member1, member2):
    """
    Hai người chỉ được tính điểm nếu
    bộ role được phép của họ giống HỆT nhau.
    """

    roles1 = get_allowed_roles(member1)
    roles2 = get_allowed_roles(member2)

    if not roles1 or not roles2:
        return False

    return roles1 == roles2


def get_role_names(member):
    names = []

    for role in member.roles:
        if role.id in ALLOWED_ROLE_IDS:
            names.append(role.name)

    return names


# ============================================================
# PAIR FUNCTIONS
# ============================================================

def get_pair_id(user1, user2):
    """
    Tạo ID cặp cố định.

    A + B
    B + A

    đều trở thành cùng một ID.
    """

    ids = sorted([user1.id, user2.id])

    return f"{ids[0]}-{ids[1]}"


def get_pair_points(guild_id, user1, user2):
    guild_id = str(guild_id)
    pair_id = get_pair_id(user1, user2)

    return points.get(
        guild_id,
        {}
    ).get(
        pair_id,
        0
    )


# ============================================================
# GIF
# ============================================================

async def get_anime_gif(reaction):
    global http_session

    url = (
        "https://api.otakugifs.xyz/gif"
        f"?reaction={reaction}"
    )

    try:
        if http_session is None:
            timeout = aiohttp.ClientTimeout(total=8)

            http_session = aiohttp.ClientSession(
                timeout=timeout
            )

        async with http_session.get(url) as response:

            if response.status != 200:
                print(
                    f"GIF API error: HTTP {response.status}"
                )
                return None

            data = await response.json()

            return data.get("url")

    except Exception as e:
        print(f"GIF error ({reaction}): {e}")
        return None


# ============================================================
# SEND POINT NOTIFICATION
# ============================================================

async def send_point_notification(
    user1,
    user2,
    amount,
    reason,
    total
):
    if POINT_CHANNEL_ID == 0:
        return

    channel = user1.guild.get_channel(
        POINT_CHANNEL_ID
    )

    if channel is None:
        print(
            f"Cannot find POINT_CHANNEL_ID: "
            f"{POINT_CHANNEL_ID}"
        )
        return

    role_names = get_role_names(user1)

    role_text = ", ".join(role_names)

    if not role_text:
        role_text = "Không xác định"

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
        print(
            "Bot does not have permission "
            "to send messages in POINT_CHANNEL_ID."
        )

    except Exception as e:
        print(
            f"Notification error: {e}"
        )


# ============================================================
# ADD PAIR POINT
# ============================================================

async def add_pair_point(
    user1,
    user2,
    amount,
    reason
):
    """
    Cộng điểm chung cho một cặp.
    """

    if not roles_same(user1, user2):
        return False

    guild_id = str(user1.guild.id)
    pair_id = get_pair_id(user1, user2)

    if guild_id not in points:
        points[guild_id] = {}

    if pair_id not in points[guild_id]:
        points[guild_id][pair_id] = 0

    points[guild_id][pair_id] += amount

    save_json(
        POINTS_FILE,
        points
    )

    total = points[guild_id][pair_id]

    print(
        f"POINT +{amount}: "
        f"{user1.display_name} + "
        f"{user2.display_name} "
        f"= {total}"
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
# VOICE DATABASE
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

    if "continuous_seconds" not in data:
        data["continuous_seconds"] = 0

    if "reward" not in data:
        data["reward"] = False

    return data


# ============================================================
# RESET VOICE
# ============================================================

def reset_continuous_voice(guild_id, user_id):
    """
    Reset chuỗi Voice khi:
    - rời Voice
    - đổi phòng Voice
    """

    data = get_voice_data(
        guild_id,
        user_id
    )

    data["continuous_seconds"] = 0

    # Cho phép nhận lại nếu bắt đầu
    # một chuỗi 100 giờ mới.
    data["reward"] = False

    save_json(
        VOICE_FILE,
        voice_time
    )

    print(
        f"VOICE RESET: {user_id}"
    )


# ============================================================
# GIVE 100 HOURS ROLE
# ============================================================

async def give_voice_reward(member):
    guild_id = str(member.guild.id)
    user_id = str(member.id)

    role = member.guild.get_role(
        VOICE_REWARD_ROLE_ID
    )

    if role is None:
        print(
            f"Reward role not found: "
            f"{VOICE_REWARD_ROLE_ID}"
        )
        return

    data = get_voice_data(
        guild_id,
        user_id
    )

    # Nếu đã đánh dấu nhận thưởng
    # thì không cấp lại.
    if data.get("reward", False):
        return

    try:

        if role not in member.roles:
            await member.add_roles(
                role,
                reason="Đạt 100 giờ Voice liên tục"
            )

        data["reward"] = True

        save_json(
            VOICE_FILE,
            voice_time
        )

        print(
            f"100 HOURS REWARD: "
            f"{member}"
        )

        if POINT_CHANNEL_ID != 0:

            channel = member.guild.get_channel(
                POINT_CHANNEL_ID
            )

            if channel is not None:

                await channel.send(
                    f"🏆 **CHÚC MỪNG!**\n"
                    f"🎧 {member.mention}\n"
                    f"⏱️ Đã đạt "
                    f"**100 giờ Voice LIÊN TỤC!**\n"
                    f"🎖️ Đã nhận role "
                    f"{role.mention}"
                )

    except discord.Forbidden:

        print(
            "Bot không có quyền cấp role."
        )

    except Exception as e:

        print(
            f"Give role error: {e}"
        )


# ============================================================
# UPDATE VOICE TIME
# ============================================================

async def update_voice_time(
    member,
    seconds
):
    """
    Cộng thời gian Voice liên tục.
    """

    data = get_voice_data(
        member.guild.id,
        member.id
    )

    if data.get("reward", False):
        return

    data["continuous_seconds"] += seconds

    current = data["continuous_seconds"]

    save_json(
        VOICE_FILE,
        voice_time
    )

    if current >= VOICE_REQUIRED_SECONDS:

        await give_voice_reward(
            member
        )


# ============================================================
# VOICE TRACKER
# ============================================================

@tasks.loop(seconds=60)
async def voice_tracker():

    now = time.time()

    for guild in bot.guilds:

        # ----------------------------------------------------
        # Người đang ở Voice
        # ----------------------------------------------------

        current_users = set()

        for member in guild.members:

            if member.bot:
                continue

            if member.voice is None:
                continue

            if member.voice.channel is None:
                continue

            current_users.add(member.id)

            key = (
                guild.id,
                member.id
            )

            channel_id = member.voice.channel.id

            # Người mới vào Voice
            if key not in voice_sessions:

                voice_sessions[key] = {
                    "channel_id": channel_id,
                    "last_check": now
                }

                continue

            session = voice_sessions[key]

            # ------------------------------------------------
            # ĐỔI PHÒNG
            # ------------------------------------------------

            if session["channel_id"] != channel_id:

                session["channel_id"] = channel_id
                session["last_check"] = now

                reset_continuous_voice(
                    guild.id,
                    member.id
                )

                continue

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

            if member.voice is None:
                continue

            if member.voice.channel is None:
                continue

            session = voice_sessions[key]

            elapsed = int(
                now - session["last_check"]
            )

            if elapsed <= 0:
                continue

            session["last_check"] = now

            await update_voice_time(
                member,
                elapsed
            )

        # ----------------------------------------------------
        # Tìm các phòng Voice
        # ----------------------------------------------------

        rooms = {}

        for member in guild.members:

            if member.bot:
                continue

            if member.voice is None:
                continue

            if member.voice.channel is None:
                continue

            channel_id = member.voice.channel.id

            if channel_id not in rooms:
                rooms[channel_id] = []

            rooms[channel_id].append(member)

        # ----------------------------------------------------
        # Tính thời gian các cặp
        # ----------------------------------------------------

        active_pairs = set()

        for members in rooms.values():

            if len(members) < 2:
                continue

            for i in range(len(members)):

                for j in range(
                    i + 1,
                    len(members)
                ):

                    user1 = members[i]
                    user2 = members[j]

                    if not roles_same(
                        user1,
                        user2
                    ):
                        continue

                    pair_id = get_pair_id(
                        user1,
                        user2
                    )

                    pair_key = (
                        f"{guild.id}:{pair_id}"
                    )

                    active_pairs.add(
                        pair_key
                    )

                    if pair_key not in pair_voice_timers:
                        pair_voice_timers[pair_key] = 0

                    pair_voice_timers[pair_key] += 60

                    # Có thể cộng nhiều lần nếu
                    # tracker bị trễ.
                    while (
                        pair_voice_timers[pair_key]
                        >= VOICE_POINT_SECONDS
                    ):

                        pair_voice_timers[pair_key] -= (
                            VOICE_POINT_SECONDS
                        )

                        await add_pair_point(
                            user1,
                            user2,
                            VOICE_POINT_AMOUNT,
                            (
                                f"🎧 Cùng Voice "
                                f"đủ {VOICE_POINT_MINUTES} "
                                f"phút."
                            )
                        )

        # ----------------------------------------------------
        # Xóa timer cặp không còn cùng Voice
        # ----------------------------------------------------

        for pair_key in list(
            pair_voice_timers.keys()
        ):

            prefix = f"{guild.id}:"

            if not pair_key.startswith(prefix):
                continue

            if pair_key not in active_pairs:

                del pair_voice_timers[
                    pair_key
                ]


# ============================================================
# MESSAGE EVENT
# ============================================================

@bot.event
async def on_message(message):

    if message.author.bot:
        return

    if message.guild is None:

        await bot.process_commands(
            message
        )

        return

    author = message.author

    # --------------------------------------------------------
    # TAG
    # --------------------------------------------------------

    for target in message.mentions:

        if target.bot:
            continue

        if target.id == author.id:
            continue

        if not roles_same(
            author,
            target
        ):
            continue

        pair_id = get_pair_id(
            author,
            target
        )

        cooldown_key = (
            f"{message.guild.id}:{pair_id}"
        )

        now = time.time()

        last_tag = tag_cooldowns.get(
            cooldown_key,
            0
        )

        if (
            now - last_tag
            < TAG_COOLDOWN_SECONDS
        ):
            continue

        tag_cooldowns[cooldown_key] = now

        await add_pair_point(
            author,
            target,
            TAG_POINT_AMOUNT,
            "🏷️ Tag nhau."
        )

    # Quan trọng:
    # Cho các command ?xxx hoạt động
    await bot.process_commands(
        message
    )


# ============================================================
# INTERACTION COMMAND HELPER
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
            f"{emoji} **{ctx.author.display_name}** "
            f"{action} chính mình..."
        )

        return

    gif_url = await get_anime_gif(
        reaction
    )

    embed = discord.Embed(
        description=(
            f"{emoji} **{ctx.author.display_name}** "
            f"{action} **{member.display_name}**!"
        ),
        color=color
    )

    if gif_url:
        embed.set_image(
            url=gif_url
        )

    await ctx.send(
        embed=embed
    )


# ============================================================
# ?OM
# ============================================================

@bot.command(
    name="om",
    aliases=["hug"
