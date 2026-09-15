import discord
from discord.ext import commands, tasks
import os
import json
import time
import aiohttp
import asyncio


# =========================================================
# CẤU HÌNH
# =========================================================

TOKEN = os.getenv("TOKEN")
PREFIX = "?"

# Kênh thông báo cộng điểm
POINT_CHANNEL_ID = int(
    os.getenv("POINT_CHANNEL_ID", "0")
)

# Database
POINTS_FILE = "points.json"
VOICE_FILE = "voice_time.json"


# =========================================================
# CẤU HÌNH ĐIỂM
# =========================================================

# Cùng Voice đủ 10 phút -> +3 điểm chung
VOICE_POINT_INTERVAL = 10
VOICE_POINT_SECONDS = VOICE_POINT_INTERVAL * 60
VOICE_POINT_AMOUNT = 3

# Tag nhau -> +1 điểm chung
TAG_POINT_AMOUNT = 1

# Cooldown tag: 5 phút / cặp
TAG_COOLDOWN = 5 * 60


# =========================================================
# CẤU HÌNH 100 GIỜ VOICE LIÊN TỤC
# =========================================================

VOICE_REWARD_ROLE_ID = 1543920448503291924

# 100 giờ = 360.000 giây
VOICE_REQUIRED_SECONDS = 100 * 60 * 60


# =========================================================
# ROLE ĐƯỢC PHÉP TÍNH ĐIỂM
# =========================================================

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


# =========================================================
# INTENTS
# =========================================================

intents = discord.Intents.default()

intents.message_content = True
intents.members = True
intents.voice_states = True


# =========================================================
# BOT
# =========================================================

bot = commands.Bot(
    command_prefix=PREFIX,
    intents=intents,
    help_command=None
)


# =========================================================
# DATABASE
# =========================================================

def load_json(filename):
    if not os.path.exists(filename):
        return {}

    try:
        with open(
            filename,
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        if isinstance(data, dict):
            return data

        return {}

    except Exception as error:
        print(
            f"❌ Không thể đọc {filename}: {error}"
        )
        return {}


def save_json(filename, data):
    try:
        temp_file = filename + ".tmp"

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=4
            )

        os.replace(temp_file, filename)

    except Exception as error:
        print(
            f"❌ Không thể lưu {filename}: {error}"
        )


points = load_json(POINTS_FILE)
voice_time = load_json(VOICE_FILE)


# =========================================================
# BỘ NHỚ TẠM
# =========================================================

# Tag cooldown
# {
#   "guild:user1-user2": timestamp
# }
tag_cooldowns = {}


# Voice session
# {
#   (guild_id, user_id): {
#       "channel_id": int,
#       "last_check": float
#   }
# }
voice_sessions = {}


# Thời gian 2 người cùng Voice
# {
#   "guild_id:user1-user2": seconds
# }
pair_voice_timers = {}


# =========================================================
# HTTP SESSION CHO GIF
# =========================================================

http_session = None


# =========================================================
# HELPER
# =========================================================

def get_allowed_roles(member):
    """
    Lấy chính xác các role nằm trong ALLOWED_ROLE_IDS.
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
    Hai người chỉ được tính điểm nếu bộ role được phép
    của họ GIỐNG HỆT NHAU.
    """

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


def get_pair_id(user1, user2):
    """
    Tạo ID cặp cố định.
    Ví dụ:
    user1 + user2
    user2 + user1

    đều trở thành cùng một pair ID.
    """

    ids = sorted(
        [
            user1.id,
            user2.id
        ]
    )

    return f"{ids[0]}-{ids[1]}"


def get_pair_points(guild_id, user1, user2):
    guild_id = str(guild_id)

    pair_id = get_pair_id(
        user1,
        user2
    )

    return points.get(
        guild_id,
        {}
    ).get(
        pair_id,
        0
    )


# =========================================================
# LẤY GIF
# =========================================================

async def get_anime_gif(reaction):
    """
    Lấy GIF từ OtakuGIFs API.
    """

    global http_session

    url = (
        "https://api.otakugifs.xyz/gif"
        f"?reaction={reaction}"
    )

    try:

        if http_session is None:
            timeout = aiohttp.ClientTimeout(
                total=8
            )

            http_session = aiohttp.ClientSession(
                timeout=timeout
            )

        async with http_session.get(url) as response:

            if response.status != 200:
                print(
                    f"❌ GIF API trả về HTTP "
                    f"{response.status}"
                )
                return None

            data = await response.json()

            gif_url = data.get("url")

            return gif_url

    except Exception as error:

        print(
            f"❌ Lỗi lấy GIF "
            f"({reaction}): {error}"
        )

        return None


# =========================================================
# CỘNG ĐIỂM CHUNG
# =========================================================

async def add_pair_point(
    user1,
    user2,
    amount,
    reason
):

    # Không cùng bộ role -> không cộng
    if not roles_same(
        user1,
        user2
    ):
        return False

    guild_id = str(
        user1.guild.id
    )

    pair_id = get_pair_id(
        user1,
        user2
    )

    # Tạo dữ liệu server
    if guild_id not in points:
        points[guild_id] = {}

    # Tạo dữ liệu cặp
    if pair_id not in points[guild_id]:
        points[guild_id][pair_id] = 0

    # Cộng điểm
    points[guild_id][pair_id] += amount

    # Lưu
    save_json(
        POINTS_FILE,
        points
    )

    total = points[guild_id][pair_id]

    print(
        f"💖 {user1.display_name} + "
        f"{user2.display_name} "
        f"-> +{amount} "
        f"(Tổng: {total})"
    )

    # Không cấu hình kênh thông báo
    if POINT_CHANNEL_ID == 0:
        return True

    channel = user1.guild.get_channel(
        POINT_CHANNEL_ID
    )

    if channel is None:
        print(
            f"⚠️ Không tìm thấy "
            f"POINT_CHANNEL_ID: "
            f"{POINT_CHANNEL_ID}"
        )
        return True

    role_names = get_role_names(
        user1
    )

    role_text = (
        ", ".join(role_names)
        if role_names
        else "Không xác định"
    )

    try:

        await channel.send(
            f"💖 **CẶP ĐƯỢC CỘNG ĐIỂM!**\n"
            f"👤 {user1.mention} ❤️ "
            f"{user2.mention}\n"
            f"🎭 Role: `{role_text}`\n"
            f"➕ **+{amount} điểm**\n"
            f"🏆 Điểm chung: **{total}**\n"
            f"📌 {reason}"
        )

    except discord.Forbidden:

        print(
            "❌ Bot không có quyền gửi "
            "tin nhắn vào POINT_CHANNEL_ID."
        )

    except Exception as error:

        print(
            f"❌ Lỗi gửi thông báo điểm: "
            f"{error}"
        )

    return True


# =========================================================
# VOICE 100 GIỜ LIÊN TỤC
# =========================================================

def get_voice_data(
    guild_id,
    user_id
):

    guild_id = str(guild_id)
    user_id = str(user_id)

    if guild_id not in voice_time:
        voice_time[guild_id] = {}

    if user_id not in voice_time[guild_id]:

        voice_time[guild_id][user_id] = {
            "continuous_seconds": 0,
            "reward": False
        }

    return voice_time[guild_id][user_id]


def reset_continuous_voice(
    guild_id,
    user_id
):

    guild_id = str(guild_id)
    user_id = str(user_id)

    if guild_id not in voice_time:
        return

    if user_id not in voice_time[guild_id]:
        return

    voice_time[guild_id][user_id][
        "continuous_seconds"
    ] = 0

    # Khi reset chuỗi thì cho phép
    # đạt 100 giờ lại trong tương lai.
    voice_time[guild_id][user_id][
        "reward"
    ] = False

    save_json(
        VOICE_FILE,
        voice_time
    )

    print(
        f"🔄 Reset Voice liên tục: "
        f"{user_id}"
    )


async def give_voice_reward(member):

    guild_id = str(
        member.guild.id
    )

    user_id = str(
        member.id
    )

    role = member.guild.get_role(
        VOICE_REWARD_ROLE_ID
    )

    if role is None:

        print(
            f"❌ Không tìm thấy role "
            f"{VOICE_REWARD_ROLE_ID}"
        )

        return

    try:

        # Cấp role nếu chưa có
        if role not in member.roles:

            await member.add_roles(
                role,
                reason="Đủ 100 giờ Voice liên tục"
            )

        data = get_voice_data(
            guild_id,
            user_id
        )

        data["reward"] = True

        save_json(
            VOICE_FILE,
            voice_time
        )

        print(
            f"🏆 {member} đã đạt "
            f"100 giờ Voice liên tục!"
        )

        # Thông báo
        if POINT_CHANNEL_ID != 0:

            channel = member.guild.get_channel(
                POINT_CHANNEL_ID
            )

            if channel:

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
            "❌ Bot không có quyền "
            "cấp role."
        )

    except Exception as error:

        print(
            f"❌ Lỗi cấp role: "
            f"{error}"
        )


async def update_continuous_voice(
    member,
    added_seconds
):

    data = get_voice_data(
        member.guild.id,
        member.id
    )

    # Nếu đã nhận role thì không cần
    # tiếp tục tính mục tiêu 100h.
    if data.get("reward", False):
        return

    data["continuous_seconds"] += (
        added_seconds
    )

    total = data[
        "continuous_seconds"
    ]

    save_json(
        VOICE_FILE,
        voice_time
    )

    if total >= VOICE_REQUIRED_SECONDS:

        await give_voice_reward(
            member
        )


# =========================================================
# VOICE TRACKER
# =========================================================

@tasks.loop(seconds=60)
async def voice_tracker():

    now = time.time()

    for guild in bot.guilds:

        current_users = set()

        # -------------------------------------------------
        # 1. LẤY NGƯỜI ĐANG Ở VOICE
        # -------------------------------------------------

        for member in guild.members:

            if member.bot:
                continue

            if member.voice is None:
                continue

            if member.voice.channel is None:
                continue

            current_users.add(
                member.id
            )

            key = (
                guild.id,
                member.id
            )

            channel_id = (
                member.voice.channel.id
            )

            # Người mới vào Voice
            if key not in voice_sessions:

                voice_sessions[key] = {
                    "channel_id": channel_id,
                    "last_check": now
                }

                continue

            session = voice_sessions[key]

            # -------------------------------------------------
            # ĐỔI KÊNH -> RESET 100 GIỜ LIÊN TỤC
            # -------------------------------------------------

            if (
                session["channel_id"]
                != channel_id
            ):

                session["channel_id"] = (
                    channel_id
                )

                session["last_check"] = (
                    now
                )

                reset_continuous_voice(
                    guild.id,
                    member.id
                )

                continue

        # -------------------------------------------------
        # 2. XỬ LÝ NGƯỜI ĐÃ RỜI VOICE
        # -------------------------------------------------

        for key in list(
            voice_sessions.keys()
        ):

            key_guild_id, user_id = key

            if key_guild_id != guild.id:
                continue

            if user_id not in current_users:

                del voice_sessions[key]

                reset_continuous_voice(
                    guild.id,
                    user_id
                )

                continue

        # -------------------------------------------------
        # 3. CỘNG THỜI GIAN VOICE
        # -------------------------------------------------

        for key in list(
            voice_sessions.keys()
        ):

            key_guild_id, user_id = key

            if key_guild_id != guild.id:
                continue

            member = guild.get_member(
                user_id
            )

            if member is None:
                continue

            if member.voice is None:
                continue

            if member.voice.channel is None:
                continue

            session = voice_sessions[key]

            elapsed = (
                now
                - session["last_check"]
            )

            if elapsed <= 0:
                continue

            session["last_check"] = now

            await update_continuous_voice(
                member,
                int(elapsed)
            )

        # -------------------------------------------------
        # 4. TÌM CÁC CẶP ĐANG CÙNG VOICE
        # -------------------------------------------------

        rooms = {}

        for member in guild.members:

            if member.bot:
                continue

            if member.voice is None:
                continue

            if member.voice.channel is None:
                continue

            channel_id = (
                member.voice.channel.id
            )

            if channel_id not in rooms:
                rooms[channel_id] = []

            rooms[channel_id].append(
                member
            )

        active_pairs = set()

        # -------------------------------------------------
        # 5. TÍNH THỜI GIAN CẶP
        # -------------------------------------------------

        for members in rooms.values():

            if len(members) < 2:
                continue

            for i in range(
                len(members)
            ):

                for j in range(
                    i + 1,
                    len(members)
                ):

                    user1 = members[i]
                    user2 = members[j]

                    # Role không giống nhau
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
                        f"{guild.id}:"
                        f"{pair_id}"
                    )

                    active_pairs.add(
                        pair_key
                    )

                    # Dùng thời gian thực tế
                    # thay vì luôn +60 giây.
                    previous = pair_voice_timers.get(
                        pair_key,
                        0
                    )

                    pair_voice_timers[
                        pair_key
                    ] = previous + 60

                    # Đủ 10 phút
                    while (
                        pair_voice_timers[
                            pair_key
                        ]
                        >= VOICE_POINT_SECONDS
                    ):

                        pair_voice_timers[
                            pair_key
                        ] -= VOICE_POINT_SECONDS

                        await add_pair_point(
                            user1,
                            user2,
                            VOICE_POINT_AMOUNT,
                            (
                                f"🎧 Cùng Voice "
                                f"đủ "
                                f"{VOICE_POINT_INTERVAL} "
                                f"phút."
                            )
                        )

        # -------------------------------------------------
        # 6. XÓA TIMER CẶP KHÔNG CÒN CÙNG VOICE
        # -------------------------------------------------

        for pair_key in list(
            pair_voice_timers.keys()
        ):

            prefix = f"{guild.id}:"

            if not pair_key.startswith(
                prefix
            ):
                continue

            if pair_key not in active_pairs:

                del pair_voice_timers[
                    pair_key
                ]


# =========================================================
# MESSAGE EVENT
# =========================================================

@bot.event
async def on_message(message):

    # Bỏ qua bot
    if message.author.bot:

        await bot.process_commands(
            message
        )

        return

    # Bỏ qua DM
    if message.guild is None:

        await bot.process_commands(
            message
        )

        return

    author = message.author

    # -----------------------------------------------------
    # TAG -> +1 ĐIỂM
    # -----------------------------------------------------

    for target in message.mentions:

        # Tag bot
        if target.bot:
            continue

        # Tự tag mình
        if target.id == author.id:
            continue

        # Role không giống
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
            f"{message.guild.id}:"
            f"{pair_id}"
        )

        now = time.time()

        last_tag = tag_cooldowns.get(
            cooldown_key,
            0
        )

        # Chưa hết cooldown
        if (
            now - last_tag
            < TAG_COOLDOWN
        ):

            print(
                f"🛑 Tag cooldown: "
                f"{author.display_name} -> "
                f"{target.display_name}"
            )

            continue

        # Ghi thời gian tag
        tag_cooldowns[
            cooldown_key
        ] = now

        await add_pair_point(
            author,
            target,
            TAG_POINT_AMOUNT,
            "🏷️ Tag nhau."
        )

    # Cho command hoạt động
    await bot.process_commands(
        message
    )


# =========================================================
# ?om
# =========================================================

@bot.command(
    name="
