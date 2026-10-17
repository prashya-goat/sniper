import asyncio
import os
from telethon import TelegramClient, functions, types, events, Button
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from flask import Flask
from threading import Thread

# --- Railway Keep-Alive Flask Server ---
app = Flask('')

@app.route('/')
def home():
    return "Telegram Smart Sniper Bot is Running!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- Configuration ---
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_USERNAME = "PARSHYA"

SESSION_DIR = "sessions"
os.makedirs(SESSION_DIR, exist_ok=True)

current_target = None
active_clients = []
is_sniper_running = False

# Temporary states for phone login conversation
user_states = {} # chat_id -> {'state': 'WAITING_PHONE'/'WAITING_OTP'/'WAITING_2FA', 'phone': ..., 'client': ...}

# --- Control Bot Client ---
control_bot = TelegramClient('bot_control_session', API_ID, API_HASH).start(bot_token=BOT_TOKEN)


# --- Smart Sniper Worker (Dynamic Timing based on Account Count) ---
async def sniper_worker(client_index, client, total_accounts):
    global is_sniper_running, current_target
    print(f"🚀 Sniper Worker {client_index}/{total_accounts} started checking @{current_target}...")
    
    # Smart gap calculation: Jitne accounts honge, us hisab se delay optimize hoga
    # Agar 5 accounts hain toh har account ke beech ka gap 10 seconds rahega
    loop_delay = max(5.0, total_accounts * 2.0)
    
    while is_sniper_running and current_target:
        try:
            result = await client(functions.account.CheckUsernameRequest(
                username=current_target
            ))
            
            if result:
                print(f"🎉 SUCCESS! Username @{current_target} is available! Grabbed by Account {client_index}")
                grabbed_user = current_target
                is_sniper_running = False  # Stop sniper after grab
                
                try:
                    # 1. Create Channel
                    channel = await client(functions.channels.CreateChannelRequest(
                        title=f"Sniped {grabbed_user}",
                        about="Secured by Telegram Sniper Bot",
                        megagroup=False
                    ))
                    channel_id = channel.chats[0].id
                    
                    # 2. Set Username
                    await client(functions.channels.UpdateUsernameRequest(
                        channel=channel_id,
                        username=grabbed_user
                    ))
                    
                    # 3. Export Invite Link
                    invite = await client(functions.messages.ExportChatInviteRequest(peer=channel_id))
                    
                    # 4. Notify Owner
                    await control_bot.send_message(
                        f"@{OWNER_USERNAME}", 
                        f"🎉 **Username Sniped Successfully!**\n\nTarget: `@{grabbed_user}`\n\n🔗 Join this channel quickly to claim ownership:\n{invite.link}"
                    )
                    
                    # 5. Wait for owner to join & transfer ownership
                    print(f"⏳ Waiting for @{OWNER_USERNAME} to join the channel for ownership transfer...")
                    while True:
                        await asyncio.sleep(5)
                        try:
                            user_entity = await control_bot.get_entity(f"@{OWNER_USERNAME}")
                            participants = await client.get_participants(channel_id, search=OWNER_USERNAME)
                            if participants:
                                await client(functions.channels.EditAdminRequest(
                                    channel=channel_id,
                                    user_id=user_entity.id,
                                    admin_rights=types.ChatAdminRights(
                                        change_info=True, post_messages=True, edit_messages=True,
                                        delete_messages=True, invite_users=True, pin_messages=True,
                                        manage_call=True, manage_topics=True, invite_link=True, admin=True
                                    ),
                                    rank="Owner"
                                ))
                                await control_bot.send_message(f"@{OWNER_USERNAME}", f"👑 Ownership transferred successfully for `@{grabbed_user}`!")
                                break
                        except Exception:
                            pass
                except Exception as ex:
                    print(f"❌ Error during channel claiming: {ex}")
                break
            else:
                print(f"[-] Account {client_index}: @{current_target} is taken.")
                
        except FloodWaitError as e:
            print(f"⚠️ Account {client_index} hit FloodWait: sleeping for {e.seconds} seconds.")
            await asyncio.sleep(e.seconds)
        except Exception:
            pass
            
        # Smart dynamic loop delay
        await asyncio.sleep(loop_delay)


# --- Inline Keyboard Menu ---
def get_main_menu_buttons():
    return [
        [Button.inline("➕ Add via String", b"add_string"), Button.inline("📱 Add via Phone", b"add_phone")],
        [Button.inline("📂 View Sessions", b"list_sessions"), Button.inline("🚀 Start Snipe", b"menu_snipe")],
        [Button.inline("🛑 Stop Sniper", b"stop_sniper")]
    ]


# --- Bot Commands & Button Handlers ---

@control_bot.on(events.NewMessage(pattern='/start'))
async def start_cmd(event):
    if event.sender.username != OWNER_USERNAME:
        return
    await event.respond(
        "🤖 **Telegram Smart Sniper Control Panel**\n\n"
        "Neche diye gaye buttons ka use karke apne sessions manage karo aur sniping control karo:",
        buttons=get_main_menu_buttons()
    )


@control_bot.on(events.CallbackQuery)
async def callback_query_handler(event):
    if event.sender.username != OWNER_USERNAME:
        await event.answer("Access Denied!", alert=True)
        return
    
    data = event.data
    chat_id = event.chat_id
    
    if data == b"add_string":
        user_states[chat_id] = {'state': 'WAITING_STRING'}
        await event.edit("📝 **Session String Add karne ke liye:**\n\nKripya apni Telethon session string yahan bhejhein:")
        
    elif data == b"add_phone":
        user_states[chat_id] = {'state': 'WAITING_PHONE'}
        await event.edit("📱 **Phone Number se Login karne ke liye:**\n\nKripya apna account ka phone number country code ke sath bhejhein (jaise `+919876543210`):")
        
    elif data == b"list_sessions":
        files = [f for f in os.listdir(SESSION_DIR) if f.endswith('.session')]
        if not files:
            await event.edit("📂 Koi session file saved nahi hai!", buttons=get_main_menu_buttons())
            return
        
        await event.edit(f"📂 Found **{len(files)}** session files. Sending them now...")
        for file in files:
            await control_bot.send_file(chat_id, os.path.join(SESSION_DIR, file), caption=f"📁 `{file}`")
        await control_bot.send_message(chat_id, "✅ Saari files bhej di gayi hain.", buttons=get_main_menu_buttons())
        
    elif data == b"menu_snipe":
        await event.edit("🎯 Target set karne ke liye command use karein:\n\n👉 `/snipe <username>`\n(Example: `/snipe PARSHYA`)", buttons=get_main_menu_buttons())
        
    elif data == b"stop_sniper":
        global is_sniper_running
        is_sniper_running = False
        await event.edit("🛑 Sniper successfully rok diya gaya hai.", buttons=get_main_menu_buttons())


# --- Conversation Handler for Adding Sessions (String or Phone/OTP) ---

@control_bot.on(events.NewMessage)
async def message_handler(event):
    if not event.is_private:
        return
    if event.sender.username != OWNER_USERNAME:
        return
    
    chat_id = event.chat_id
    text = event.text.strip()
    
    # Agar koi command hai toh use ye handler ignore karega (command handlers alag hain)
    if text.startswith('/'):
        return
        
    if chat_id not in user_states:
        return
        
    state_data = user_states[chat_id]
    state = state_data.get('state')
    
    # 1. Handling Session String Input
    if state == 'WAITING_STRING':
        del user_states[chat_id]
        try:
            await event.respond("⏳ Testing session string...")
            test_client = TelegramClient(StringSession(text), API_ID, API_HASH)
            await test_client.connect()
            
            if await test_client.is_user_authorized():
                me = await test_client.get_me()
                name = f"{me.first_name} {me.last_name or ''}".strip()
                phone = str(me.phone) if hasattr(me, 'phone') else "NoPhone"
                
                file_name = f"session_{me.id}.session"
                file_path = os.path.join(SESSION_DIR, file_name)
                
                await test_client.disconnect()
                
                # Save as file session
                file_client = TelegramClient(file_path, API_ID, API_HASH)
                await file_client.connect()
                temp_str_client = TelegramClient(StringSession(text), API_ID, API_HASH)
                await temp_str_client.connect()
                
                file_client.session.auth_key = temp_str_client.session.auth_key
                file_client.session.dc_id = temp_str_client.session.dc_id
                file_client.session.server_address = temp_str_client.session.server_address
                file_client.session.port = temp_str_client.session.port
                file_client.session.save()
                
                await temp_str_client.disconnect()
                await file_client.disconnect()
                
                await event.respond(f"✅ **Session Saved Successfully via String!**\n👤 Name: {name}\n📱 Phone: `{phone}`", buttons=get_main_menu_buttons())
            else:
                await event.respond("❌ Session invalid ya unauthorized hai!", buttons=get_main_menu_buttons())
                await test_client.disconnect()
        except Exception as e:
            await event.respond(f"❌ Error: {e}", buttons=get_main_menu_buttons())
            
    # 2. Handling Phone Login - Step 1: Phone Number
    elif state == 'WAITING_PHONE':
        phone_number = text
        try:
            await event.respond("⏳ Sending OTP request to Telegram...")
            temp_file = f"temp_login_{chat_id}.session"
            client = TelegramClient(temp_file, API_ID, API_HASH)
            await client.connect()
            
            sent_code = await client.send_code_request(phone_number)
            user_states[chat_id] = {
                'state': 'WAITING_OTP',
                'phone': phone_number,
                'client': client,
                'phone_code_hash': sent_code.phone_code_hash,
                'temp_file': temp_file
            }
            await event.respond("✅ OTP bhej diya gaya hai!\n\nKripya apne Telegram app par aaya hua **OTP code** yahan bhejhein:")
        except Exception as e:
            await event.respond(f"❌ Error sending code: {e}", buttons=get_main_menu_buttons())
            del user_states[chat_id]
            
    # 3. Handling Phone Login - Step 2: OTP Code
    elif state == 'WAITING_OTP':
        otp_code = text
        client = state_data['client']
        phone = state_data['phone']
        phone_code_hash = state_data['phone_code_hash']
        temp_file = state_data['temp_file']
        
        try:
            await client.sign_in(phone=phone, code=otp_code, phone_code_hash=phone_code_hash)
            # Agar successfully login ho gaya
            me = await client.get_me()
            await client.disconnect()
            
            # Rename temp file to permanent session file
            perm_file = os.path.join(SESSION_DIR, f"session_{me.id}.session")
            if os.path.exists(perm_file):
                os.remove(perm_file)
            os.rename(temp_file, perm_file)
            
            del user_states[chat_id]
            await event.respond(f"✅ **Account Login Successful & Saved!**\n👤 Name: {me.first_name}\n📱 Phone: `{phone}`", buttons=get_main_menu_buttons())
            
        except SessionPasswordNeededError:
            # 2FA Password required
            user_states[chat_id] = {
                'state': 'WAITING_2FA',
                'client': client,
                'temp_file': temp_file
            }
            await event.respond("🔐 Account par **2FA (Two-Step Verification)** laga hua hai.\n\nKripya apna **2FA Password** yahan bhejhein:")
        except Exception as e:
            await event.respond(f"❌ Error signing in: {e}", buttons=get_main_menu_buttons())
            try:
                await client.disconnect()
            except:
                pass
            del user_states[chat_id]
            
    # 4. Handling Phone Login - Step 3: 2FA Password
    elif state == 'WAITING_2FA':
        password = text
        client = state_data['client']
        temp_file = state_data['temp_file']
        
        try:
            await client.sign_in(password=password)
            me = await client.get_me()
            await client.disconnect()
            
            perm_file = os.path.join(SESSION_DIR, f"session_{me.id}.session")
            if os.path.exists(perm_file):
                os.remove(perm_file)
            os.rename(temp_file, perm_file)
            
            del user_states[chat_id]
            await event.respond(f"✅ **2FA Verified & Session Saved!**\n👤 Name: {me.first_name}", buttons=get_main_menu_buttons())
            
        except Exception as e:
            await event.respond(f"❌ Invalid 2FA password: {e}", buttons=get_main_menu_buttons())
            try:
                await client.disconnect()
            except:
                pass
            del user_states[chat_id]


# --- Snipe Command ---

@control_bot.on(events.NewMessage(pattern='/snipe'))
async def snipe_cmd(event):
    global is_sniper_running, current_target, active_clients
    if event.sender.username != OWNER_USERNAME:
        return
    
    args = event.text.split(' ', 1)
    if len(args) < 2:
        await event.respond("⚠️ Format: `/snipe <username>` (e.g., `/snipe PARSHYA`)")
        return
        
    current_target = args[1].strip().replace("@", "")
    
    if is_sniper_running:
        await event.respond(f"🔄 Target updated to `@{current_target}`!")
        return
        
    session_files = [os.path.join(SESSION_DIR, f) for f in os.listdir(SESSION_DIR) if f.endswith('.session')]
    if not session_files:
        await event.respond("❌ Koi session file nahi mili! Pehle sessions add karo.", buttons=get_main_menu_buttons())
        return
        
    active_clients.clear()
    for file_path in session_files:
        try:
            client = TelegramClient(file_path, API_ID, API_HASH)
            await client.connect()
            if await client.is_user_authorized():
                active_clients.append(client)
        except Exception:
            pass
            
    total_accounts = len(active_clients)
    if total_accounts == 0:
        await event.respond("❌ Ek bhi valid session file nahi chali!")
        return
        
    is_sniper_running = True
    await event.respond(
        f"🚀 **Sniper Started!**\n"
        f"🎯 Target: `@{current_target}`\n"
        f"👥 Active Accounts: **{total_accounts}**\n"
        f"⚡ Dynamic Time Management Enabled (Staggered start + smart loop delay).",
        buttons=get_main_menu_buttons()
    )
    
    # Staggered start gap (Har account ke beech 3-5 seconds ka gap taaki flood wait na aaye)
    tasks = []
    for idx, client in enumerate(active_clients):
        tasks.append(asyncio.create_task(sniper_worker(idx + 1, client, total_accounts)))
        await asyncio.sleep(3.0)


# --- Main Execution ---
if __name__ == '__main__':
    keep_alive()
    print("Smart sniper control panel started...")
    control_bot.run_until_disconnected()
