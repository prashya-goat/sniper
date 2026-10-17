import asyncio
import os
import time
import threading
from flask import Flask
from telethon import TelegramClient, events, functions
from telethon.sessions import StringSession
from telethon.errors import (
    UsernameOccupiedError,
    UsernameInvalidError,
    FloodWaitError
)

# --- MASTER CONFIGURATION ---
API_ID = int(os.environ.get("API_ID", 35450000))
API_HASH = os.environ.get("API_HASH", "2f06604ccfb6670846f4640ac40b8f97")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8894074405:AAHUbw_kkSMt4CXWHFxxu1LTj46OO5Sj7B0")

# Load 5 Accounts from Railway Environment Variables
ACCOUNTS = {}
for i in range(1, 6):
    sess = os.environ.get(f"SESSION_{i}", "").strip()
    if sess:
        ACCOUNTS[f"Account_{i}"] = sess

# --- FLASK KEEP-ALIVE SERVER ---
app = Flask(__name__)

@app.route('/')
def home():
    return "5-Account Staggered Sniper Bot is active 24/7!", 200

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

# --- STATE MANAGEMENT ---
is_sniping = False
active_target = None
snipe_tasks = []

bot = TelegramClient('bot_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)

# --- COMMANDS ---
@bot.on(events.NewMessage(pattern=r'/start'))
async def start_cmd(event):
    if event.is_group or event.is_channel:
        return
    help_text = (
        "🤖 **5-Account Staggered Sniper Bot**\n\n"
        f"📂 **Configured Accounts:** {len(ACCOUNTS)} / 5 loaded from ENV.\n\n"
        "⚡ **Commands:**\n"
        "• `/snipe <username>` - Starts staggered rotation check\n"
        "• `/stop` - Stop all sniping\n"
        "• `/status` - Check current status"
    )
    await event.respond(help_text)

# --- STAGGERED WORKER WITH 40S COOLDOWN ---
async def staggered_worker(acc_name, session_str, target_username, initial_delay, event):
    global is_sniping
    client = TelegramClient(StringSession(session_str), API_ID, API_HASH, flood_sleep_threshold=0)
    try:
        await client.connect()
    except Exception:
        return

    # Initial stagger delay so accounts don't fire all at once
    if initial_delay > 0:
        await asyncio.sleep(initial_delay)

    checks = 0
    start_time = time.time()

    while is_sniping:
        checks += 1
        try:
            # Silent availability check
            is_free = await client(functions.account.CheckUsernameRequest(username=target_username))
            
            if is_free:
                elapsed = round(time.time() - start_time, 2)
                await event.respond(f"🔥 [FREE FOUND] `@{target_username}` is free! Claiming via `{acc_name}`...")

                # Create channel and claim username
                channel = await client(functions.channels.CreateChannelRequest(
                    title=target_username,
                    about="Sniper Channel",
                    megagroup=False
                ))

                await client(functions.channels.UpdateUsernameRequest(
                    channel=channel.chats[0].id,
                    username=target_username
                ))

                await event.respond(
                    f"🎉 **SUCCESS! Username Sniped Successfully!**\n\n"
                    f"📌 Username: `@{target_username}`\n"
                    f"👤 Account Used: `{acc_name}`\n"
                    f"⏱️ Time Taken: **{elapsed} seconds**\n"
                    f"🔍 Total Checks by this account: {checks}"
                )
                is_sniping = False
                break
            else:
                # Still occupied: wait 40 seconds before THIS account checks again
                await asyncio.sleep(40.0)

        except FloodWaitError as e:
            # If server gives a flood wait, sleep for that exact duration safely
            await asyncio.sleep(e.seconds)
        except Exception:
            await asyncio.sleep(40.0)

    try:
        await client.disconnect()
    except:
        pass

@bot.on(events.NewMessage(pattern=r'/snipe\s+(.+)'))
async def snipe_cmd(event):
    global snipe_tasks, is_sniping, active_target
    if event.is_group or event.is_channel:
        return
    if is_sniping:
        await event.respond(f"⚠️ Already sniping `@{active_target}`! Send `/stop` first.")
        return
        
    if len(ACCOUNTS) == 0:
        await event.respond(f"❌ No sessions found! Please set `SESSION_1` to `SESSION_5` in Railway Environment Variables.")
        return

    target_username = event.pattern_match.group(1).strip().lstrip('@')
    is_sniping = True
    active_target = target_username
    snipe_tasks = []

    await event.respond(
        f"🎯 **Staggered Rotation Sniper Started!**\n"
        f"Target: `@{target_username}`\n"
        f"📂 Active Accounts: {len(ACCOUNTS)}\n"
        f"⚡ *Each account will maintain a 40-second cooldown with smooth rotation.*"
    )

    # Launch tasks with an 8-second stagger gap between each account
    for index, (acc_name, str_session) in enumerate(ACCOUNTS.items()):
        stagger_delay = index * 8.0  # 0s, 8s, 16s, 24s, 32s
        task = asyncio.create_task(staggered_worker(acc_name, str_session, target_username, stagger_delay, event))
        snipe_tasks.append(task)

@bot.on(events.NewMessage(pattern=r'/stop'))
async def stop_cmd(event):
    if event.is_group or event.is_channel:
        return
    global is_sniping, snipe_tasks
    if not is_sniping:
        await event.respond("ℹ️ No active sniping running.")
        return
    is_sniping = False
    for task in snipe_tasks:
        task.cancel()
    await event.respond("🛑 Sniping stopped successfully.")

@bot.on(events.NewMessage(pattern=r'/status'))
async def status_cmd(event):
    if event.is_group or event.is_channel:
        return
    if is_sniping:
        await event.respond(f"🟢 Staggered Sniping active on `@{active_target}` with {len(ACCOUNTS)} accounts.")
    else:
        await event.respond("⚪ Idle.")

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    print("[*] 5-Account Staggered Sniper Bot running 24/7.")
    bot.run_until_disconnected()

if __name__ == '__main__':
    main()
