import discord
from discord.ext import commands, tasks
import os
import json
import time
import aiohttp

=====================================================

CẤU HÌNH

=====================================================

TOKEN = os.getenv("TOKEN")
PREFIX = "?"

ID kênh thông báo

POINT_CHANNEL_ID = int(os.getenv("POINT_CHANNEL_ID", "0"))

Database

POINTS_FILE = "points.json"
VOICE_FILE = "voice_time.json"

=====================================================

CẤU HÌNH ĐIỂM

=====================================================

Cùng Voice đủ 10 phút -> +3 điểm chung

VOICE_POINT_INTERVAL = 10  # Phút
VOICE_POINT_SECONDS = VOICE_POINT_INTERVAL * 60  # 600 giây
VOICE_POINT_AMOUNT = 3

Tag -> +1 điểm chung

TAG_POINT_AMOUNT = 1

Chống spam tag (5 phút / cặp)

TAG_COOLDOWN = 300

=====================================================

CẤU HÌNH 100 GIỜ VOICE LIÊN TỤC

=====================================================

Role nhận khi đủ 100 giờ liên tục

VOICE_REWARD_ROLE_ID = 1543920448503291924

100 giờ (tính theo giây)

VOICE_REQUIRED_SECONDS = 100 * 60 * 60

=====================================================

ROLE ĐƯỢC PHÉP TÍNH ĐIỂM

=====================================================

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

=====================================================

HÀM LẤY GIF CHUẨN TỪ API

=====================================================

async def get_anime_gif(reaction: str) -> str:
"""Lấy ảnh GIF chuẩn theo đúng hành động từ OtakuGIFs API"""
url = f"https://api.otakugifs.xyz/gif?reaction={reaction}"
try:
async with aiohttp.ClientSession() as session:
async with session.get(url, timeout=5) as resp:
if resp.status == 200:
data = await resp.json()
return data.get("url")
except Exception as e:
print(f"❌ Lỗi lấy GIF ({reaction}): {e}")
return None

=====================================================

INTENTS & BOT INITIALIZATION

=====================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

=====================================================

DATABASE - ĐIỂM & VOICE TIME

=====================================================

def load_json(filename):
if not os.path.exists(filename):
return {}
try:
with open(filename, "r", encoding="utf-8") as f:
return json.load(f)
except Exception as e:
print(f"❌ Lỗi đọc {filename}: {e}")
return {}

points = load_json(POINTS_FILE)
voice_time = load_json(VOICE_FILE)

def save_json(filename, data):
try:
with open(filename, "w", encoding="utf-8") as f:
json.dump(data, f, ensure_ascii=False, indent=4)
except Exception as e:
print(f"❌ Lỗi lưu {filename}: {e}")

=====================================================

THEO DÕI SPAM & VOICE

=====================================================

tag_cooldowns = {}
voice_sessions = {}  # Cấu trúc: {(guild_id, user_id): {"channel_id": int, "last_check": float}}
pair_voice_timers = {}  # Theo dõi thời gian gom chung của cặp: {pair_key: float_seconds}

=====================================================

HELPER FUNCTIONS

=====================================================

def get_allowed_roles(member):
return tuple(sorted(role.id for role in member.roles if role.id in ALLOWED_ROLE_IDS))

def roles_same(member1, member2):
roles1 = get_allowed_roles(member1)
roles2 = get_allowed_roles(member2)
if not roles1 or not roles2:
return False
return roles1 == roles2

def get_role_names(member):
return [role.name for role in member.roles if role.id in ALLOWED_ROLE_IDS]

def get_pair_id(user1, user2):
ids = sorted([user1.id, user2.id])
return f"{ids[0]}-{ids[1]}"

def get_pair_points(guild_id, user1, user2):
guild_id = str(guild_id)
pid = get_pair_id(user1, user2)
return points.get(guild_id, {}).get(pid, 0)

=====================================================

XỬ LÝ ĐIỂM VÀ THỜI GIAN VOICE LIÊN TỤC

=====================================================

async def add_pair_point(user1, user2, amount, reason):
if not roles_same(user1, user2):
return False

guild_id = str(user1.guild.id)  
pid = get_pair_id(user1, user2)  

if guild_id not in points:  
    points[guild_id] = {}  
if pid not in points[guild_id]:  
    points[guild_id][pid] = 0  

points[guild_id][pid] += amount  
save_json(POINTS_FILE, points)  

total = points[guild_id][pid]  
print(f"💖 {user1.display_name} + {user2.display_name} -> +{amount} (Tổng: {total})")  

if POINT_CHANNEL_ID == 0:  
    return True  

channel = user1.guild.get_channel(POINT_CHANNEL_ID)  
if channel is None:  
    return True  

role_names = get_role_names(user1)  
role_text = ", ".join(role_names)  

try:  
    await channel.send(  
        f"💖 **CẶP ĐƯỢC CỘNG ĐIỂM!**\n"  
        f"👤 {user1.mention} ❤️ {user2.mention}\n"  
        f"🎭 Role: `{role_text}`\n"  
        f"➕ **+{amount} điểm**\n"  
        f"🏆 Điểm chung: **{total}**\n"  
        f"📌 {reason}"  
    )  
except Exception as e:  
    print(f"❌ Lỗi gửi thông báo: {e}")  

return True

async def update_continuous_voice(member, added_seconds):
"""Cập nhật thời gian voice liên tục và kiểm tra nhận role."""
guild_id = str(member.guild.id)
user_id = str(member.id)

if guild_id not in voice_time:  
    voice_time[guild_id] = {}  
if user_id not in voice_time[guild_id]:  
    voice_time[guild_id][user_id] = {"continuous_seconds": 0, "reward": False}  

# Cộng dồn thời gian liên tục  
voice_time[guild_id][user_id]["continuous_seconds"] += added_seconds  
total_continuous = voice_time[guild_id][user_id]["continuous_seconds"]  

save_json(VOICE_FILE, voice_time)  

# Kiểm tra điều kiện 100 giờ liên tục  
reward_given = voice_time[guild_id][user_id].get("reward", False)  
if total_continuous >= VOICE_REQUIRED_SECONDS and not reward_given:  
    await give_voice_reward(member)

def reset_continuous_voice(guild_id, user_id):
"""Reset thời gian voice liên tục về 0 khi user rời kênh voice hoặc đổi kênh."""
g_id = str(guild_id)
u_id = str(user_id)

if g_id in voice_time and u_id in voice_time[g_id]:  
    voice_time[g_id][u_id]["continuous_seconds"] = 0  
    save_json(VOICE_FILE, voice_time)

async def give_voice_reward(member):
guild_id = str(member.guild.id)
user_id = str(member.id)
role = member.guild.get_role(VOICE_REWARD_ROLE_ID)

if role is None:  
    print(f"❌ Không tìm thấy Role {VOICE_REWARD_ROLE_ID}")  
    return  

try:  
    if role not in member.roles:  
        await member.add_roles(role, reason="Đủ 100 giờ Voice liên tục")  

    if guild_id not in voice_time:  
        voice_time[guild_id] = {}  
    if user_id not in voice_time[guild_id]:  
        voice_time[guild_id][user_id] = {"continuous_seconds": VOICE_REQUIRED_SECONDS, "reward": True}  
    else:  
        voice_time[guild_id][user_id]["reward"] = True  

    save_json(VOICE_FILE, voice_time)  
    print(f"🏆 {member} đã đạt 100 giờ Voice liên tục!")  

    if POINT_CHANNEL_ID != 0:  
        channel = member.guild.get_channel(POINT_CHANNEL_ID)  
        if channel:  
            await channel.send(  
                f"🏆 **CHÚC MỪNG!**\n"  
                f"🎧 {member.mention}\n"  
                f"⏱️ Đã đạt **100 giờ Voice LIÊN TỤC**!\n"  
                f"🎖️ Đã nhận role {role.mention}"  
            )  
except discord.Forbidden:  
    print("❌ Bot không có quyền cấp role.")  
except Exception as e:  
    print(f"❌ Lỗi cấp role: {e}")

=====================================================

TASKS & EVENTS

=====================================================

@tasks.loop(seconds=60)
async def voice_tracker():
now = time.time()
for guild in bot.guilds:
current_users = set()

# 1. Lấy danh sách thành viên đang trong voice  
    for member in guild.members:  
        if member.bot or member.voice is None or member.voice.channel is None:  
            continue  

        current_users.add(member.id)  
        key = (guild.id, member.id)  

        if key not in voice_sessions:  
            voice_sessions[key] = {  
                "channel_id": member.voice.channel.id,  
                "last_check": now  
            }  
        else:  
            session = voice_sessions[key]  
            # Nếu đổi kênh voice -> Reset thời gian liên tục về 0  
            if session["channel_id"] != member.voice.channel.id:  
                session["channel_id"] = member.voice.channel.id  
                session["last_check"] = now  
                reset_continuous_voice(guild.id, member.id)  

    # 2. Xử lý những người đã rời Voice (Reset chuỗi liên tục)  
    for key in list(voice_sessions.keys()):  
        key_guild_id, user_id = key  
        if key_guild_id != guild.id:  
            continue  

        if user_id not in current_users:  
            # Người dùng đã thoát voice -> Reset thời gian voice liên tục về 0  
            del voice_sessions[key]  
            reset_continuous_voice(guild.id, user_id)  
            continue  

        member = guild.get_member(user_id)  
        if member is None:  
            continue  

        session = voice_sessions[key]  
        elapsed = now - session["last_check"]  
        if elapsed <= 0:  
            continue  

        session["last_check"] = now  
        # Cộng thêm thời gian vừa ngồi  
        await update_continuous_voice(member, int(elapsed))  

    # 3. Tính điểm chung cho các cặp cùng Voice (Đủ 10 phút = 600s -> +3 điểm)  
    rooms = {}  
    for member in guild.members:  
        if member.bot or member.voice is None or member.voice.channel is None:  
            continue  
        channel_id = member.voice.channel.id  
        if channel_id not in rooms:  
            rooms[channel_id] = []  
        rooms[channel_id].append(member)  

    active_pairs = set()  
    for members in rooms.values():  
        if len(members) < 2:  
            continue  
        for i in range(len(members)):  
            for j in range(i + 1, len(members)):  
                user1, user2 = members[i], members[j]  
                if not roles_same(user1, user2):  
                    continue  

                pid = get_pair_id(user1, user2)  
                pair_key = f"{guild.id}:{pid}"  
                active_pairs.add(pair_key)  

                # Tích lũy thời gian cặp cùng ngồi voice (+60 giây mỗi chu kỳ loop)  
                pair_voice_timers[pair_key] = pair_voice_timers.get(pair_key, 0) + 60  

                # Đủ 10 phút (600 giây) thì cộng điểm và reset bộ đếm cặp  
                if pair_voice_timers[pair_key] >= VOICE_POINT_SECONDS:  
                    pair_voice_timers[pair_key] -= VOICE_POINT_SECONDS  
                    await add_pair_point(  
                        user1, user2, VOICE_POINT_AMOUNT, f"🎧 Cùng Voice Room đủ {VOICE_POINT_INTERVAL} phút."  
                    )  

    # Xóa các cặp không còn ngồi chung voice với nhau  
    for p_key in list(pair_voice_timers.keys()):  
        if p_key.startswith(f"{guild.id}:") and p_key not in active_pairs:  
            del pair_voice_timers[p_key]

@bot.event
async def on_message(message):
if message.author.bot or message.guild is None:
await bot.process_commands(message)
return

author = message.author  

for target in message.mentions:  
    if target.bot or target.id == author.id:  
        continue  
    if not roles_same(author, target):  
        continue  

    pid = get_pair_id(author, target)  
    cooldown_key = f"{message.guild.id}:{pid}"  
    now = time.time()  
    last_tag = tag_cooldowns.get(cooldown_key, 0)  

    if now - last_tag < TAG_COOLDOWN:  
        print(f"🛑 Tag spam: {author.display_name} -> {target.display_name}")  
        continue  

    tag_cooldowns[cooldown_key] = now  
    await add_pair_point(author, target, TAG_POINT_AMOUNT, "🏷️ Tag nhau.")  

await bot.process_commands(message)

=====================================================

COMMANDS HÀNH ĐỘNG TƯƠNG TÁC

=====================================================

@bot.command(name="om", aliases=["hug"])
async def hug(ctx, member: discord.Member = None):
if member is None:
await ctx.send("❌ Bạn cần tag người muốn ôm! Ví dụ: ?om @user")
return

if member.id == ctx.author.id:  
    await ctx.send(f"**{ctx.author.display_name}** tự ôm lấy chính mình... (thương thương ❤️)")  
    return  

gif_url = await get_anime_gif("hug")  
embed = discord.Embed(  
    description=f"🤗 **{ctx.author.display_name}** đã ôm **{member.display_name}** thật chặt!",  
    color=discord.Color.pink()  
)  
if gif_url:  
    embed.set_image(url=gif_url)  
await ctx.send(embed=embed)

@bot.command(name="hon", aliases=["kiss"])
async def kiss(ctx, member: discord.Member = None):
if member is None:
await ctx.send("❌ Bạn cần tag người muốn hôn! Ví dụ: ?hon @user")
return

if member.id == ctx.author.id:  
    await ctx.send(f"**{ctx.author.display_name}** tự hôn vào gương... 😳")  
    return  

gif_url = await get_anime_gif("kiss")  
embed = discord.Embed(  
    description=f"💋 **{ctx.author.display_name}** đã trao một nụ hôn ngọt ngào cho **{member.display_name}**!",  
    color=discord.Color.red()  
)  
if gif_url:  
    embed.set_image(url=gif_url)  
await ctx.send(embed=embed)

@bot.command(name="xoadau", aliases=["pat"])
async def pat(ctx, member: discord.Member = None):
if member is None:
await ctx.send("❌ Bạn cần tag người muốn xoa đầu! Ví dụ: ?xoadau @user")
return

if member.id == ctx.author.id:  
    await ctx.send(f"**{ctx.author.display_name}** tự xoa đầu mình... (ngoan lắm 🫳)")  
    return  

gif_url = await get_anime_gif("pat")  
embed = discord.Embed(  
    description=f"🫳 **{ctx.author.display_name}** xoa đầu **{member.display_name}** thật dịu dàng!",  
    color=discord.Color.light_grey()  
)  
if gif_url:  
    embed.set_image(url=gif_url)  
await ctx.send(embed=embed)

@bot.command(name="thomma", aliases=["cheek"])
async def cheek(ctx, member: discord.Member = None):
if member is None:
await ctx.send("❌ Bạn cần tag người muốn thơm má! Ví dụ: ?thomma @user")
return

if member.id == ctx.author.id:  
    await ctx.send(f"**{ctx.author.display_name}** tự thơm vào tay... 💕")  
    return  

gif_url = await get_anime_gif("kiss")  
embed = discord.Embed(  
    description=f"😚 **{ctx.author.display_name}** nhẹ nhàng thơm vào má **{member.display_name}**!",  
    color=discord.Color.purple()  
)  
if gif_url:  
    embed.set_image(url=gif_url)  
await ctx.send(embed=embed)

@bot.command(name="canyeu", aliases=["bite"])
async def bite(ctx, member: discord.Member = None):
if member is None:
await ctx.send("❌ Bạn cần tag người muốn cắn yêu! Ví dụ: ?canyeu @user")
return

if member.id == ctx.author.id:  
    await ctx.send(f"**{ctx.author.display_name}** tự cắn vào tay mình... đau đấy! 😬")  
    return  

gif_url = await get_anime_gif("bite")  
embed = discord.Embed(  
    description=f"🦷 **{ctx.author.display_name}** cắn nhẹ **{member.display_name}** một cái thật yêu!",  
    color=discord.Color.orange()  
)  
if gif_url:  
    embed.set_image(url=gif_url)  
await ctx.send(embed=embed)

=====================================================

COMMANDS QUẢN LÝ ĐIỂM & VOICE

=====================================================

@bot.command()
async def diem(ctx, member: discord.Member = None):
if member is None:
await ctx.send("❌ Dùng: ?diem @người")
return
if member.bot:
await ctx.send("❌ Không thể xem điểm với bot.")
return
if not roles_same(ctx.author, member):
await ctx.send("❌ Hai người không có bộ role giống nhau.")
return

score = get_pair_points(ctx.guild.id, ctx.author, member)  
await ctx.send(  
    f"💖 **ĐIỂM CHUNG**\n\n"  
    f"👤 {ctx.author.mention}\n"  
    f"❤️ {member.mention}\n\n"  
    f"🏆 **{score} điểm**"  
)

@bot.command()
async def gio(ctx):
guild_id = str(ctx.guild.id)
user_id = str(ctx.author.id)

data = voice_time.get(guild_id, {}).get(user_id, {"continuous_seconds": 0, "reward": False})  
seconds = data.get("continuous_seconds", 0)  
hours = seconds / 3600  
remaining = max(0, VOICE_REQUIRED_SECONDS - seconds)  
remaining_hours = remaining / 3600  

await ctx.send(  
    f"🎧 **THỜI GIAN VOICE LIÊN TỤC**\n\n"  
    f"👤 {ctx.author.mention}\n"  
    f"⏱️ Đã Voice liên tục: **{hours:.2f} giờ**\n"  
    f"🏆 Mục tiêu: **100 giờ liên tục**\n"  
    f"⌛ Còn lại: **{remaining_hours:.2f} giờ**\n"  
    f"⚠️ *Lưu ý: Rời kênh Voice hoặc chuyển phòng sẽ reset thời gian liên tục về 0 giờ.*"  
)

@bot.command()
async def top(ctx):
guild_id = str(ctx.guild.id)
data = points.get(guild_id, {})

if not data:  
    await ctx.send("📊 Chưa có cặp nào có điểm.")  
    return  

ranking = sorted(data.items(), key=lambda x: x[1], reverse=True)[:10]  
text = "🏆 **TOP CẶP ĐIỂM**\n\n"  

for index, (pid, score) in enumerate(ranking, 1):  
    try:  
        id1, id2 = pid.split("-")  
        member1 = ctx.guild.get_member(int(id1))  
        member2 = ctx.guild.get_member(int(id2))  

        name1 = member1.display_name if member1 else f"User {id1}"  
        name2 = member2.display_name if member2 else f"User {id2}"  

        text += f"**{index}.** {name1} ❤️ {name2} — **{score} điểm**\n"  
    except Exception:  
        continue  

await ctx.send(text)

@bot.command()
@commands.has_permissions(administrator=True)
async def resetdiem(ctx):
guild_id = str(ctx.guild.id)
points[guild_id] = {}
save_json(POINTS_FILE, points)
await ctx.send("🗑️ Đã reset toàn bộ điểm.")

=====================================================

LỖI COMMAND & READY

=====================================================

@bot.event
async def on_command_error(ctx, error):
if isinstance(error, commands.MissingPermissions):
await ctx.send("❌ Bạn không có quyền dùng lệnh này.")
return
if isinstance(error, commands.MemberNotFound):
await ctx.send("❌ Không tìm thấy người dùng.")
return
if isinstance(error, commands.MissingRequiredArgument):
await ctx.send("❌ Thiếu tham số bắt buộc.")
return
if isinstance(error, commands.CommandNotFound):
return
print(f"❌ Command error: {error}")

@bot.event
async def on_ready():
print("=" * 55)
print(f"✅ BOT ONLINE: {bot.user}")
print(f"🏠 Server: {len(bot.guilds)}")
print(f"🎧 Voice: {VOICE_POINT_INTERVAL} phút = +{VOICE_POINT_AMOUNT} điểm")
print("🏷️ Tag: +1 điểm / 5 phút / cặp")
print("🏆 100 giờ Voice LIÊN TỤC -> tự cấp role")
print("=" * 55)

if not voice_tracker.is_running():  
    voice_tracker.start()

=====================================================

CHẠY BOT

=====================================================

if name == "main":
if not TOKEN:
raise RuntimeError("❌ Chưa có TOKEN trong Railway Variables!")
bot.run(TOKEN)
