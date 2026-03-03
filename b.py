import logging
import random
import asyncio
import requests
import json
import os
import time
import psutil
import re
import base64
import hashlib
from datetime import datetime, timedelta
from collections import defaultdict
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)
from telegram.error import TelegramError, BadRequest, RetryAfter, TimedOut

# -------------------- الإعدادات الأساسية --------------------

BOT_TOKEN = "7879134683:AAFfMQ-VLedBl1VlMyR5mj6JCyjC-7Rb30g"
LOG_CHAT_ID = -1002322209314

CHANNELS = [
    "@Ahmaed_dev1",
    "@wolvesteamcrack",
    "@ahmaeedinfo",
]

DATA_FILE = "bot_data.json"
REFERRAL_SECRET = "MySecretKey2025"  # مفتاح سري لتشفير روابط الإحالة

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

STEP_SENDER, STEP_OTP = range(2)

HEADERS = {
    'User-Agent': "MobileApp/3.0.2",
    'Accept': "application/json",
    'Content-Type': "application/json",
    'accept-language': "ar",
    'Connection': "keep-alive"
}

semaphore = asyncio.Semaphore(300)
data_lock = asyncio.Lock()  # قفل للتعامل الآمن مع البيانات

# -------------------- دوال مساعدة للإحالات --------------------

def encode_referral(user_id: int) -> str:
    """تشفير معرف المستخدم في رابط إحالة آمن"""
    data = f"{user_id}:{hashlib.md5(f'{user_id}{REFERRAL_SECRET}'.encode()).hexdigest()[:8]}"
    return base64.urlsafe_b64encode(data.encode()).decode().rstrip("=")

def decode_referral(encoded: str) -> int | None:
    """فك تشفير رابط الإحالة والتحقق من صحته، يعيد user_id إذا كان صحيحاً"""
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode()
        parts = decoded.split(":")
        if len(parts) != 2:
            return None
        user_id_str, checksum = parts
        if not user_id_str.isdigit():
            return None
        user_id = int(user_id_str)
        expected = hashlib.md5(f"{user_id}{REFERRAL_SECRET}".encode()).hexdigest()[:8]
        if checksum == expected:
            return user_id
    except Exception:
        return None
    return None

# -------------------- دوال مساعدة عامة --------------------

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # التأكد من وجود الحقول الجديدة
                if "referrals" not in data:
                    data["referrals"] = []
                if "referral_stats" not in data:
                    data["referral_stats"] = {}
                if "total_success" not in data:
                    data["total_success"] = 0
                if "total_failed" not in data:
                    data["total_failed"] = 0
                return data
        except json.JSONDecodeError:
            logging.error("خطأ في قراءة ملف البيانات، إنشاء ملف جديد")
            return {
                "users": {},
                "referrals": [],
                "referral_stats": {},
                "total_activations": 0,
                "total_users": 0,
                "total_success": 0,
                "total_failed": 0
            }
    return {
        "users": {},
        "referrals": [],
        "referral_stats": {},
        "total_activations": 0,
        "total_users": 0,
        "total_success": 0,
        "total_failed": 0
    }

async def save_data(data):
    async with data_lock:
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"خطأ في حفظ البيانات: {e}")

def mask_phone(phone):
    if not phone:
        return "غير معروف"
    phone = str(phone).strip()
    if phone.startswith("213"):
        phone = "0" + phone[3:]
    if phone.startswith("0") and len(phone) >= 10:
        return phone[:2] + "••••" + phone[-2:]
    return phone

def is_phone_number(text):
    cleaned = re.sub(r'\s+', '', text)
    patterns = [r'^07\d{8}$']
    return any(re.match(pattern, cleaned) for pattern in patterns)

def format_num(phone):
    phone = str(phone).strip()
    if phone.startswith('0'):
        return "213" + phone[1:]
    return phone

def generate_random_djezzy_no():
    prefix = random.choice(["077", "078", "079"])
    return prefix + "".join(str(random.randint(0, 9)) for _ in range(7))

# -------------------- دوال الطلب مع إعادة المحاولة --------------------

def make_request_with_retry(method, url, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            if method.lower() == 'post':
                response = requests.post(url, **kwargs)
            else:
                response = requests.get(url, **kwargs)
            
            if response.status_code in [200, 201]:
                return response
            
            if response.status_code >= 500 or response.status_code == 429:
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 2
                    logging.warning(f"⚠️ خطأ {response.status_code}، إعادة المحاولة بعد {wait_time} ثواني")
                    time.sleep(wait_time)
                    continue
                else:
                    return response
            else:
                return response
                
        except requests.exceptions.RequestException as e:
            logging.error(f"❌ خطأ في الطلب (محاولة {attempt+1}): {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                logging.info(f"⏳ إعادة المحاولة بعد {wait_time} ثواني")
                time.sleep(wait_time)
            else:
                return None
    return None

# -------------------- دوال API جيزي --------------------

async def request_otp(msisdn):
    url = "https://apim.djezzy.dz/mobile-api/oauth2/registration"
    params = {'msisdn': msisdn, 'client_id': "87pIExRhxBb3_wGsA5eSEfyATloa", 'scope': "smsotp"}
    payload = {"consent-agreement": [{"marketing-notifications": False}], "is-consent": True}
    
    response = make_request_with_retry(
        'post', 
        url, 
        params=params, 
        json=payload, 
        headers=HEADERS,
        timeout=15
    )
    
    if response:
        return response.status_code
    return 500

async def delete_invitation(sender_no, target_f, token):
    """حذف الرقم المدعو بعد التفعيل الناجح"""
    url = f"https://apim.djezzy.dz/mobile-api/api/v1/services/mgm/delete-invitation/{sender_no}"
    payload = {"msisdnReciever": int(target_f)}
    response = make_request_with_retry(
        'post',
        url,
        json=payload,
        headers={**HEADERS, 'authorization': token},
        timeout=15
    )
    if response and response.status_code == 200:
        logging.info(f"✅ تم حذف الرقم {target_f} بنجاح")
        return True
    else:
        logging.warning(f"⚠️ فشل حذف الرقم {target_f}: {response.status_code if response else 'لا استجابة'}")
        return False

# -------------------- دوال التحقق من الاشتراك --------------------

async def safe_get_chat_member(bot, chat_id, user_id, max_retries=3):
    for attempt in range(max_retries):
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            return member
            
        except json.JSONDecodeError as e:
            logging.warning(f"⚠️ خطأ JSON في المحاولة {attempt + 1} للقناة {chat_id}: {e}")
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 3
                await asyncio.sleep(wait_time)
            else:
                return None
                
        except TimedOut as e:
            if attempt < max_retries - 1:
                wait_time = (attempt + 1) * 2
                await asyncio.sleep(wait_time)
            else:
                return None
                
        except RetryAfter as e:
            wait_time = e.retry_after if hasattr(e, 'retry_after') else (attempt + 1) * 2
            await asyncio.sleep(wait_time)
            
        except BadRequest as e:
            logging.error(f"❌ خطأ في الطلب للقناة {chat_id}: {e}")
            return None
            
        except Exception as e:
            logging.error(f"❌ خطأ غير متوقع: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep((attempt + 1) * 2)
            else:
                return None
    return None

async def get_not_joined(bot, user_id):
    not_joined = []
    for ch in CHANNELS:
        try:
            member = await safe_get_chat_member(bot, ch, user_id)
            if member and hasattr(member, 'status'):
                if member.status in ["left", "kicked"]:
                    not_joined.append(ch)
            else:
                not_joined.append(ch)
        except Exception as e:
            logging.error(f"❌ خطأ في التحقق من القناة {ch}: {e}")
            not_joined.append(ch)
    return not_joined

def sub_keyboard(channels):
    buttons = [[InlineKeyboardButton(f"🔔 اشترك في {ch}", url=f"https://t.me/{ch.replace('@','')}")] for ch in channels]
    buttons.append([InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)

# -------------------- دالة معالجة الإحالة الجديدة --------------------

async def process_referral(data, referrer_id, referred_user_id, timestamp):
    """تسجيل إحالة جديدة في قائمة الإحالات (active = True)"""
    # التحقق من أن المحيل ليس نفسه المُحال
    if referrer_id == referred_user_id:
        return False, "self_referral"
    # التحقق من وجود المحيل في قاعدة البيانات
    if str(referrer_id) not in data["users"]:
        return False, "referrer_not_found"
    # التحقق من أن المُحال ليس له إحالة سابقة
    for ref in data["referrals"]:
        if ref["referred"] == referred_user_id and ref.get("active", False):
            return False, "already_referred"
    # إضافة الإحالة
    data["referrals"].append({
        "referrer": referrer_id,
        "referred": referred_user_id,
        "timestamp": timestamp,
        "active": True
    })
    return True, "success"

# -------------------- بداية البوت --------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        # استخراج referrer من الرابط (deep link)
        referrer_id = None
        referral_message = None
        if context.args and len(context.args) > 0:
            encoded = context.args[0]
            referrer_id = decode_referral(encoded)
            if referrer_id == user_id:
                referrer_id = None  # منع الإحالة الذاتية
            elif referrer_id:
                # محاولة الحصول على اسم المحيل لاستخدامه في الرسالة
                try:
                    referrer_chat = await context.bot.get_chat(referrer_id)
                    referrer_name = referrer_chat.full_name
                    referral_message = f"👋 مرحباً! لقد دخلت عبر رابط صديقك {referrer_name}.\n✅ سيتم إضافة نقطة له بعد إكمال الاشتراك."
                except:
                    referral_message = "👋 مرحباً! لقد دخلت عبر رابط أحد الأصدقاء.\n✅ سيتم إضافة نقطة له بعد إكمال الاشتراك."

        not_joined = await get_not_joined(context.bot, user_id)
        
        if not_joined:
            # إرسال رسالة الترحيب مع رسالة الإحالة إن وجدت
            welcome_text = "🌟 **مرحباً يا بطل!** 🌟\n\n✨ لاستخدام البوت يجب الاشتراك في القنوات التالية أولاً:\n"
            if referral_message:
                welcome_text = f"{referral_message}\n\n{welcome_text}"
            await update.message.reply_text(
                welcome_text,
                reply_markup=sub_keyboard(not_joined),
                parse_mode="Markdown"
            )
            # تخزين referrer_id في context.user_data لاستخدامه بعد التحقق
            if referrer_id:
                context.user_data["pending_referrer"] = referrer_id
            return ConversationHandler.END

        # المستخدم مشترك بالفعل
        data = await load_data_async()
        user_str = str(user_id)
        is_new = user_str not in data["users"]
        
        # إذا كان المستخدم جديداً وهناك referrer صالح
        if is_new and referrer_id:
            # تسجيل الإحالة
            success, reason = await process_referral(data, referrer_id, user_id, time.time())
            if success:
                # تحديث إحصائيات المحيل (اختياري)
                pass

        if is_new:
            # إضافة المستخدم الجديد إلى قاعدة البيانات
            data["users"][user_str] = {
                "phone": None,
                "token": None,
                "token_expiry": 0,
                "activations_count": 0,
                "last_activation": 0,
                "registered": time.time(),
                "referred_by": referrer_id
            }
            data["total_users"] = len(data["users"])
            await save_data(data)
            
            # إرسال إشعار دخول عضو جديد إلى مجموعة الإدمن
            if LOG_CHAT_ID:
                user = update.effective_user
                full_name = user.full_name
                username = f"@{user.username}" if user.username else "لا يوجد"
                referrer_info = f"\n👥 **جاء عبر:** {referrer_id if referrer_id else 'مباشر'}"
                join_msg = (
                    f"👋 **دخول عضو جديد**\n\n"
                    f"👤 **الاسم:** {full_name}\n"
                    f"🆔 **المعرف:** {username}\n"
                    f"🔢 **الايدي:** `{user_id}`\n"
                    f"📅 **التاريخ:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"📊 **إجمالي الأعضاء:** {data['total_users']}"
                    f"{referrer_info}"
                )
                try:
                    await context.bot.send_message(chat_id=LOG_CHAT_ID, text=join_msg, parse_mode="Markdown")
                except Exception as e:
                    logging.error(f"فشل إرسال إشعار العضو الجديد: {e}")
        else:
            # المستخدم موجود مسبقاً
            pass

        # رسالة الترحيب الرئيسية
        welcome_msg = (
            "🎉 **أهلاً وسهلاً بك في بوت جيزي لتفعيل 1 غيغا مجاني!** 🎉\n\n"
            "⚡ **المميزات:**\n"
            "🔹 تفعيل سريع وآمن 100%\n"
            "🔹 خصوصية تامة لرقم هاتفك\n"
            "🔹 إحصائيات دقيقة لتفعيلاتك\n"
            "🔹 نظام إحالات بجوائز قيمة 🏆\n\n"
            "📲 **الطريقة بسيطة:**\n"
            "1️⃣ أرسل رقم هاتفك (يبدأ بـ 07، مثال: `07xxxxxxxx`)\n"
            "2️⃣ استلم رمز التحقق عبر SMS\n"
            "3️⃣ أرسل الرمز واستمتع بالغيغا المجانية!\n\n"
            "🔥 **انطلق الآن وأرسل رقمك** 🔥"
        )
        
        # تصميم الأزرار في صفوف (صف لكل زر) - يمكن تعديلها حسب الرغبة
        # هنا جعلنا كل زر في صف منفصل كما طلب المستخدم "خط مثل هذا كلمة احمد احــــمــــد" ربما يقصد التباعد
        # نضع الأزرار في أعمدة متعددة إذا أردنا تقليل عدد الأسطر
        keyboard = [
            [InlineKeyboardButton("🏆 المتصدرين", callback_data="leaderboard")],
            [InlineKeyboardButton("ℹ️ معلومات عن البوت", callback_data="about")],
            [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats")],
            [InlineKeyboardButton("👥 رابط الإحالة الخاص بي", callback_data="my_referrals")]
        ]
        
        await update.message.reply_text(
            welcome_msg,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        try:
            await update.message.reply_sticker(sticker="CAACAgIAAxkBAAETVydiZiwhH_fMn2x-CK8ZZSHklAREWQACHgAD9oK6D71hz3MWpjrmJAQ")
        except:
            pass
        
        context.user_data["conversation_state"] = STEP_SENDER
        return STEP_SENDER
        
    except Exception as e:
        logging.error(f"❌ خطأ في start: {e}")
        await update.message.reply_text("⚠️ حدث خطأ، الرجاء المحاولة مرة أخرى")
        return ConversationHandler.END

async def load_data_async():
    """نسخة غير متزامنة من load_data (للاستخدام داخل الدوال غير المتزامنة)"""
    return load_data()

# -------------------- تحقق الاشتراك --------------------

async def check_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        not_joined = await get_not_joined(context.bot, user_id)
        
        if not_joined:
            await query.answer("❌ مازلت لم تشترك في كل القنوات!", show_alert=True)
            return
        
        # بعد التحقق من الاشتراك، نعالج الإحالة المعلقة إن وجدت
        data = await load_data_async()
        user_str = str(user_id)
        is_new = user_str not in data["users"]
        referrer_id = context.user_data.get("pending_referrer")
        
        if is_new and referrer_id:
            success, reason = await process_referral(data, referrer_id, user_id, time.time())
            if success:
                # إضافة المستخدم إلى قاعدة البيانات
                data["users"][user_str] = {
                    "phone": None,
                    "token": None,
                    "token_expiry": 0,
                    "activations_count": 0,
                    "last_activation": 0,
                    "registered": time.time(),
                    "referred_by": referrer_id
                }
                data["total_users"] = len(data["users"])
                await save_data(data)
                # إرسال إشعار للإدمن (اختياري)
                if LOG_CHAT_ID:
                    user = update.effective_user
                    full_name = user.full_name
                    username = f"@{user.username}" if user.username else "لا يوجد"
                    join_msg = (
                        f"👋 **دخول عضو جديد عبر إحالة**\n\n"
                        f"👤 **الاسم:** {full_name}\n"
                        f"🆔 **المعرف:** {username}\n"
                        f"🔢 **الايدي:** `{user_id}`\n"
                        f"👥 **المحيل:** {referrer_id}\n"
                        f"📅 **التاريخ:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    try:
                        await context.bot.send_message(chat_id=LOG_CHAT_ID, text=join_msg, parse_mode="Markdown")
                    except Exception as e:
                        logging.error(f"فشل إرسال إشعار العضو الجديد: {e}")
            # إزالة المعلقة
            context.user_data.pop("pending_referrer", None)
        
        await query.edit_message_text(
            "✅ **تم التحقق بنجاح!** ✨\n\n"
            "📲 **أرسل رقم هاتفك الآن** (يبدأ بـ 07، مثال: `07xxxxxxxx`)",
            parse_mode="Markdown"
        )
        context.user_data["conversation_state"] = STEP_SENDER
        return STEP_SENDER
        
    except Exception as e:
        logging.error(f"❌ خطأ في check_sub: {e}")
        await query.answer("⚠️ حدث خطأ", show_alert=True)
        return

# -------------------- استقبال الرقم --------------------

async def handle_sender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sender_raw = update.message.text.strip()
        
        if not re.match(r'^07\d{8}$', sender_raw):
            await update.message.reply_text(
                "❌ **رقم غير صحيح!**\n\n"
                "🔹 يجب أن يكون رقم جيزي صحيح يبدأ بـ **07** ويتكون من 10 أرقام.\n"
                "📌 مثال: `07xxxxxxxx`",
                parse_mode="Markdown"
            )
            return STEP_SENDER

        sender = format_num(sender_raw)
        status = await request_otp(sender)
        
        if status in [200, 201]:
            context.user_data["sender"] = sender
            cancel_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ إلغاء العملية", callback_data="cancel")]
            ])
            await update.message.reply_text(
                "✅ **تم إرسال رمز التحقق إلى هاتفك بنجاح!** 📩\n\n"
                "🔢 أرسل الرمز المكون من **6 أرقام** الآن 👇",
                parse_mode="Markdown",
                reply_markup=cancel_keyboard
            )
            context.user_data["conversation_state"] = STEP_OTP
            return STEP_OTP
        else:
            await update.message.reply_text(
                "❌ **فشل إرسال الرمز**\n\n"
                "🔸 قد يكون الرقم غير صحيح أو الخدمة مشغولة مؤقتاً.\n"
                "🔸 يرجى التحقق من الرقم والمحاولة مرة أخرى.\n"
                "🔸 اكتب /start للبدء من جديد.",
                parse_mode="Markdown"
            )
            context.user_data.clear()
            return ConversationHandler.END
            
    except Exception as e:
        logging.error(f"❌ خطأ في handle_sender: {e}")
        await update.message.reply_text("⚠️ حدث خطأ، الرجاء المحاولة مرة أخرى")
        context.user_data.clear()
        return ConversationHandler.END

# -------------------- إلغاء العملية --------------------

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالج إلغاء العملية"""
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    await query.edit_message_text(
        "❌ **تم إلغاء العملية**\n\n"
        "يمكنك البدء من جديد بكتابة /start",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# -------------------- التحقق من OTP --------------------

async def verify_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        sender_no = context.user_data.get("sender")
        
        if not sender_no:
            await update.message.reply_text("⚠️ انتهت الجلسة، اكتب /start للبدء من جديد")
            context.user_data.clear()
            return ConversationHandler.END
            
        otp = update.message.text.strip()
        
        if not otp.isdigit() or len(otp) != 6:
            await update.message.reply_text(
                "❌ **الرمز يجب أن يكون 6 أرقام فقط**\n"
                "🔢 حاول مرة أخرى بإدخال الرمز الصحيح",
                parse_mode="Markdown"
            )
            return STEP_OTP

        payload = {
            'otp': otp,
            'mobileNumber': sender_no,
            'scope': "djezzyAppV2",
            'client_id': "87pIExRhxBb3_wGsA5eSEfyATloa",
            'client_secret': "uf82p68Bgisp8Yg1Uz8Pf6_v1XYa",
            'grant_type': "mobile"
        }
        
        await asyncio.sleep(1.5)
        token = None
        
        response = make_request_with_retry(
            'post',
            "https://apim.djezzy.dz/mobile-api/oauth2/token",
            data=payload,
            headers={'User-Agent': "MobileApp/3.0.2", 'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=15
        )
        
        if response and response.status_code == 200:
            try:
                data_json = response.json()
                token = f"Bearer {data_json.get('access_token')}"
            except json.JSONDecodeError as e:
                logging.error(f"❌ REQUESTS JSON ERROR: {e}, Response: {response.text[:200]}")
                await update.message.reply_text(f"⚠️ استجابة غير متوقعة من الخادم:\n`{response.text[:200]}`", parse_mode="Markdown")
        else:
            if response:
                await update.message.reply_text(f"⚠️ فشل التحقق، رمز الحالة: {response.status_code}\nرد الخادم: `{response.text[:200]}`", parse_mode="Markdown")
            else:
                await update.message.reply_text("⚠️ فشل الاتصال بالخادم، يرجى المحاولة لاحقاً")
        
        if token:
            expiry = time.time() + 300
            data = await load_data_async()
            user_str = str(user_id)
            if user_str not in data["users"]:
                data["users"][user_str] = {}
            data["users"][user_str]["phone"] = sender_no
            data["users"][user_str]["token"] = token
            data["users"][user_str]["token_expiry"] = expiry
            data["users"][user_str]["activations_count"] = data["users"][user_str].get("activations_count", 0)
            data["users"][user_str]["last_activation"] = data["users"][user_str].get("last_activation", 0)
            await save_data(data)
        
            await update.message.reply_text(
                "✅ **تم التحقق بنجاح!** ✨\n\n⏳ جاري تفعيل 1 غيغا... يرجى الانتظار",
                parse_mode="Markdown"
            )
            try:
                await update.message.reply_sticker(sticker="CAACAgIAAxkBAAETVydiZiwhH_fMn2x-CK8ZZSHklAREWQACHgAD9oK6D71hz3MWpjrmJAQ")
            except:
                pass
            await single_attempt(update, context, token, sender_no, user_id)
        else:
            await update.message.reply_text(
                "❌ **الكود غير صحيح أو انتهت صلاحيته**\n\n"
                "🔸 يرجى المحاولة مرة أخرى بكتابة /start",
                parse_mode="Markdown"
            )
            context.user_data.clear()
            return ConversationHandler.END
            
    except Exception as e:
        logging.error(f"❌ خطأ في verify_otp: {e}")
        await update.message.reply_text("⚠️ حدث خطأ، الرجاء المحاولة مرة أخرى")
        context.user_data.clear()
        return ConversationHandler.END

async def send_safe_reply(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None, parse_mode="Markdown"):
    try:
        if update.callback_query and update.callback_query.message:
            await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        elif update.message:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await context.bot.send_message(chat_id=update.effective_user.id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        logging.error(f"❌ REPLY ERROR: {e}")

async def single_attempt(update: Update, context: ContextTypes.DEFAULT_TYPE, token, sender_no, user_id):
    async with semaphore:
        try:
            max_retries = 5
            success = False
            last_error = None
            used_targets = []

            for attempt in range(max_retries):
                target = generate_random_djezzy_no()
                target_f = format_num(target)
                used_targets.append(target_f)
                
                inv_url = f"https://apim.djezzy.dz/mobile-api/api/v1/services/mgm/send-invitation/{sender_no}"
                inv_response = make_request_with_retry(
                    'post',
                    inv_url,
                    json={"msisdnReciever": target_f},
                    headers={**HEADERS, 'authorization': token},
                    timeout=15
                )
                
                if not inv_response:
                    last_error = "فشل الاتصال بالخادم أثناء إرسال الدعوة"
                    continue
                
                inv_text = inv_response.text
                
                if inv_response.status_code in [200, 201]:
                    await send_safe_reply(update, context, f"✅ تم إرسال الدعوة إلى رقم {mask_phone(target)} بنجاح!", parse_mode="Markdown")
                    
                    await request_otp(target_f)
                    await asyncio.sleep(2)
                    
                    act_url = f"https://apim.djezzy.dz/mobile-api/api/v1/services/mgm/activate-reward/{sender_no}"
                    act_response = make_request_with_retry(
                        'post',
                        act_url,
                        json={"packageCode": "MGMBONUS1Go"},
                        headers={**HEADERS, 'authorization': token},
                        timeout=15
                    )
                    
                    if not act_response:
                        last_error = "فشل الاتصال بالخادم أثناء التفعيل"
                        continue
                    
                    act_text = act_response.text
                    
                    if act_response.status_code in [200, 201]:
                        success = True
                        await delete_invitation(sender_no, target_f, token)
                        
                        data = await load_data_async()
                        user_str = str(user_id)
                        data["users"][user_str]["activations_count"] = data["users"][user_str].get("activations_count", 0) + 1
                        data["users"][user_str]["last_activation"] = time.time()
                        data["total_activations"] += 1
                        data["total_success"] = data.get("total_success", 0) + 1
                        await save_data(data)
                        
                        masked = mask_phone(sender_no)
                        expiry_time = datetime.now() + timedelta(hours=24)
                        expiry_str = expiry_time.strftime("%Y-%m-%d %H:%M:%S")
                        
                        user = update.effective_user
                        full_name = user.full_name
                        username = f"@{user.username}" if user.username else "لا يوجد"
                        
                        success_msg = (
                            f"🎉 **مبروك يا بطل!** 🎉\n\n"
                            f"✅ **تم تفعيل 1 غيغا بنجاح** على رقم {masked} ✨\n\n"
                            f"👤 **الاسم:** {full_name}\n"
                            f"🆔 **اليوزر:** {username}\n"
                            f"🔢 **الايدي:** `{user_id}`\n"
                            f"📱 **رقم جيزي:** {masked}\n"
                            f"📅 **تاريخ التفعيل:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"⏳ **ينتهي في:** {expiry_str}\n\n"
                            f"📊 **إحصائياتك:**\n"
                            f"🔹 عدد التفعيلات: {data['users'][user_str]['activations_count']}\n"
                            f"🔹 إجمالي المستخدمين: {data['total_users']}\n"
                            f"🔹 إجمالي التفعيلات: {data['total_activations']}\n\n"
                            f"🔥 **عد غداً لاستلام غيغا جديدة!** 🔥"
                        )
                        
                        await send_safe_reply(
                            update, context,
                            success_msg,
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("🔄 تفعيل مرة أخرى", callback_data="reactivate")],
                                [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats")],
                                [InlineKeyboardButton("🏆 المتصدرين", callback_data="leaderboard")]
                            ]),
                            parse_mode="Markdown"
                        )
                        
                        try:
                            await context.bot.send_sticker(
                                chat_id=update.effective_user.id,
                                sticker="CAACAgIAAxkBAAETVydiZiwhH_fMn2x-CK8ZZSHklAREWQACHgAD9oK6D71hz3MWpjrmJAQ"
                            )
                        except:
                            pass
                        
                        if LOG_CHAT_ID:
                            log_msg = (
                                f"🎉 **تفعيل جديد** 🎉\n\n"
                                f"👤 **الاسم:** {full_name}\n"
                                f"🆔 **اليوزر:** {username}\n"
                                f"🔢 **الايدي:** `{user_id}`\n"
                                f"📱 **رقم جيزي:** {masked}\n"
                                f"📅 **تاريخ التفعيل:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                                f"📊 **تفعيلاته:** {data['users'][user_str]['activations_count']}\n"
                                f"🌐 **إجمالي التفعيلات:** {data['total_activations']}"
                            )
                            await context.bot.send_message(
                                chat_id=LOG_CHAT_ID,
                                text=log_msg,
                                parse_mode="Markdown"
                            )
                        
                        break
                        
                    else:
                        if "already" in act_text.lower() or "used" in act_text.lower():
                            last_error = "⚠️ **لقد استفدت من العرض من قبل**\n📅 حاول بعد 24 ساعة من آخر تفعيل."
                            data = await load_data_async()
                            user_str = str(user_id)
                            last_act = data["users"].get(user_str, {}).get("last_activation", 0)
                            if last_act:
                                last_time = datetime.fromtimestamp(last_act).strftime("%Y-%m-%d %H:%M:%S")
                                next_time = datetime.fromtimestamp(last_act + 24*3600).strftime("%Y-%m-%d %H:%M:%S")
                                last_error += f"\nآخر تفعيل كان في: {last_time}\nيمكنك التفعيل مجدداً بعد: {next_time}"
                            
                            user_message = (
                                "❌ **لا يمكنك التفعيل الآن.**\n\n"
                                "⏳ لقد استفدت من العرض خلال آخر 24 ساعة.\n"
                                "🕒 يرجى الانتظار حتى اكتمال 24 ساعة من آخر تفعيل لك."
                            )
                            await send_safe_reply(update, context, user_message, parse_mode="Markdown")
                            
                            data = await load_data_async()
                            data["total_failed"] = data.get("total_failed", 0) + 1
                            await save_data(data)
                            
                            await send_failure_notification(update, context, user_id, last_error, sender_no)
                            return
                        else:
                            last_error = f"❌ **فشل التفعيل**\n📋 رد الخادم: `{act_text[:200]}`"
                            continue
                
                elif inv_response.status_code == 404:
                    logging.info(f"⚠️ الرقم {target_f} غير موجود، تجربة رقم آخر...")
                    last_error = f"⚠️ الرقم {mask_phone(target)} غير موجود، جاري تجربة رقم آخر..."
                    await send_safe_reply(update, context, last_error, parse_mode="Markdown")
                    continue
                    
                elif inv_response.status_code == 400:
                    if "maximum number of invitations" in inv_text.lower():
                        last_error = "⚠️ **لقد وصلت إلى الحد الأقصى لعدد الدعوات (5) يومياً.**\n📅 يرجى الانتظار 24 ساعة قبل إعادة المحاولة."
                        user_message = (
                            "❌ **لقد وصلت إلى الحد الأقصى للدعوات (5) يومياً.**\n\n"
                            "📅 يرجى الانتظار 24 ساعة من آخر تفعيل قبل إعادة المحاولة.\n"
                            "إذا كنت قد فعلت اليوم، فستتمكن غداً بإذن الله."
                        )
                        await send_safe_reply(update, context, user_message, parse_mode="Markdown")
                        
                        data = await load_data_async()
                        data["total_failed"] = data.get("total_failed", 0) + 1
                        await save_data(data)
                        
                        await send_failure_notification(update, context, user_id, last_error, sender_no)
                        return
                    else:
                        last_error = f"❌ خطأ في إرسال الدعوة: {inv_text[:200]}"
                        user_message = (
                            "❌ **عذراً، لم نتمكن من إرسال الدعوة.**\n\n"
                            "📌 قد يكون هناك مشكلة مؤقتة في الخدمة.\n"
                            "🕒 يرجى الانتظار 24 ساعة من آخر تفعيل والمحاولة مرة أخرى."
                        )
                        await send_safe_reply(update, context, user_message, parse_mode="Markdown")
                        
                        data = await load_data_async()
                        data["total_failed"] = data.get("total_failed", 0) + 1
                        await save_data(data)
                        
                        await send_failure_notification(update, context, user_id, last_error, sender_no)
                        return
                else:
                    last_error = f"❌ فشل إرسال الدعوة (كود {inv_response.status_code}): {inv_text[:200]}"
                    continue
            
            if not success:
                user_message = (
                    "❌ **عذراً، لم نتمكن من إتمام التفعيل.**\n\n"
                    "📌 **الأسباب المحتملة:**\n"
                    "• لقد استخدمت الحد الأقصى من الدعوات اليومية (5 مرات).\n"
                    "• قد يكون قد مر أقل من 24 ساعة على آخر تفعيل لك.\n"
                    "• قد تكون هناك مشكلة مؤقتة في الخدمة.\n\n"
                    "🕒 **يرجى الانتظار 24 ساعة من آخر تفعيل والمحاولة مرة أخرى.**\n"
                    "إذا استمرت المشكلة، تواصل مع الدعم الفني."
                )
                await send_safe_reply(update, context, user_message, parse_mode="Markdown")
                
                data = await load_data_async()
                data["total_failed"] = data.get("total_failed", 0) + 1
                await save_data(data)
                
                await send_failure_notification(update, context, user_id, last_error, sender_no)
                
        except Exception as e:
            logging.error(f"❌ EXEC ERROR: {e}")
            user_message = (
                "❌ حدث خطأ غير متوقع. يرجى المحاولة لاحقاً.\n\n"
                "إذا استمرت المشكلة، تواصل مع الدعم الفني."
            )
            await send_safe_reply(update, context, user_message, parse_mode="Markdown")
            
            data = await load_data_async()
            data["total_failed"] = data.get("total_failed", 0) + 1
            await save_data(data)
            
            await send_failure_notification(update, context, user_id, str(e)[:200], sender_no)

async def send_failure_notification(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, error_msg, phone=None):
    if not LOG_CHAT_ID:
        return
    try:
        user = update.effective_user
        full_name = user.full_name
        username = f"@{user.username}" if user.username else "لا يوجد"
        masked_phone = mask_phone(phone) if phone else "غير معروف"
        
        fail_msg = (
            f"❌ **فشل تفعيل** ❌\n\n"
            f"👤 **الاسم:** {full_name}\n"
            f"🆔 **المعرف:** {username}\n"
            f"🔢 **الايدي:** `{user_id}`\n"
            f"📱 **الرقم:** {masked_phone}\n"
            f"📅 **الوقت:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"⚠️ **السبب التقني:** {error_msg}"
        )
        await context.bot.send_message(chat_id=LOG_CHAT_ID, text=fail_msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"فشل إرسال إشعار الفشل: {e}")

# -------------------- أوامر وإحصائيات الإحالات --------------------

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض لوحة المتصدرين لأكثر 20 شخص جمع إحالات نشطة"""
    data = await load_data_async()
    # حساب عدد الإحالات النشطة لكل محيل
    referral_count = defaultdict(int)
    for ref in data["referrals"]:
        if ref.get("active", False):
            referral_count[ref["referrer"]] += 1
    
    # ترتيب تنازلي
    sorted_referrers = sorted(referral_count.items(), key=lambda x: x[1], reverse=True)[:20]
    
    if not sorted_referrers:
        text = "🏆 **لا توجد إحالات بعد**\nكن أول من يدعو أصدقاءه!"
        reply_markup = None
    else:
        text = "🏆 **أكثر 20 شخص جمع إحالات** 🏆\n\n"
        keyboard = []
        for i, (uid, count) in enumerate(sorted_referrers, 1):
            try:
                chat = await context.bot.get_chat(uid)
                name = chat.full_name
                username = chat.username
                display_name = f"@{username}" if username else name
            except:
                display_name = f"مستخدم {uid}"
            
            text += f"{i}. {display_name} — `{count}` إحالة\n"
            # نضيف زر لكل مستخدم (اختياري)
            keyboard.append([InlineKeyboardButton(display_name, url=f"tg://user?id={uid}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)

async def my_referrals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """عرض إحصائيات الإحالات الخاصة بالمستخدم"""
    user_id = update.effective_user.id
    data = await load_data_async()
    # عدد الإحالات النشطة التي قام بها
    active_count = sum(1 for ref in data["referrals"] if ref["referrer"] == user_id and ref.get("active", False))
    # عدد الإحالات الكلي (قد يكون غير نشط)
    total_count = sum(1 for ref in data["referrals"] if ref["referrer"] == user_id)
    
    # رابط الإحالة الخاص به
    bot_username = (await context.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start={encode_referral(user_id)}"
    
    text = (
        f"📊 **إحصائيات إحالاتك** 📊\n\n"
        f"👥 **عدد الإحالات النشطة:** {active_count}\n"
        f"📌 **إجمالي الإحالات:** {total_count}\n\n"
        f"🔗 **رابط الإحالة الخاص بك:**\n`{ref_link}`\n\n"
        f"شارك الرابط مع أصدقائك لكسب المزيد!"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown")
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode="Markdown")

# -------------------- الوظيفة الدورية لفحص الإحالات النشطة --------------------

async def check_referrals_job(context: ContextTypes.DEFAULT_TYPE):
    """وظيفة دورية: تفحص جميع المستخدمين المدعويين وتجعل الإحالة غير نشطة إذا غادروا القنوات أو حظروا البوت"""
    logging.info("🔍 بدء فحص الإحالات النشطة...")
    data = await load_data_async()
    changed = False
    # نأخذ نسخة من قائمة الإحالات لأننا قد نعدلها
    for ref in data["referrals"]:
        if not ref.get("active", False):
            continue
        referred_id = ref["referred"]
        # التحقق من اشتراك المدعو في القنوات
        not_joined = await get_not_joined(context.bot, referred_id)
        if not_joined:
            # المدعو لم يعد مشتركاً، نجعل الإحالة غير نشطة
            ref["active"] = False
            changed = True
            logging.info(f"إلغاء إحالة للمحيل {ref['referrer']} بسبب مغادرة المدعو {referred_id}")
    if changed:
        await save_data(data)
        logging.info("✅ تم تحديث الإحالات بعد الفحص")

# -------------------- المعالجات الأخرى --------------------

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = await load_data_async()
        user_id = str(update.effective_user.id)
        user_data = data["users"].get(user_id, {})
        activations = user_data.get("activations_count", 0)
        last_act = user_data.get("last_activation", 0)
        last_str = datetime.fromtimestamp(last_act).strftime("%Y-%m-%d %H:%M") if last_act else "لم يفعل بعد"
        masked = mask_phone(user_data.get("phone")) if user_data.get("phone") else "غير معروف"
        
        user = update.effective_user
        full_name = user.full_name
        username = f"@{user.username}" if user.username else "لا يوجد"

        total_success = data.get("total_success", 0)
        total_failed = data.get("total_failed", 0)
        total_attempts = total_success + total_failed
        success_rate = (total_success / total_attempts * 100) if total_attempts > 0 else 0

        # إحصائيات الإحالات
        active_refs = sum(1 for ref in data["referrals"] if ref["referrer"] == int(user_id) and ref.get("active", False))
        total_refs = sum(1 for ref in data["referrals"] if ref["referrer"] == int(user_id))

        stats_msg = (
            f"📊 **إحصائياتك الشخصية** 📊\n\n"
            f"👤 **الاسم:** {full_name}\n"
            f"🆔 **اليوزر:** {username}\n"
            f"🔢 **الايدي:** `{update.effective_user.id}`\n"
            f"📱 **رقم جيزي:** {masked}\n"
            f"✅ **عدد التفعيلات:** {activations}\n"
            f"📅 **آخر تفعيل:** {last_str}\n"
            f"👥 **الإحالات النشطة:** {active_refs}\n"
            f"📌 **إجمالي الإحالات:** {total_refs}\n\n"
            f"🌐 **إحصائيات عامة**\n"
            f"👥 إجمالي المستخدمين: {data['total_users']}\n"
            f"🎁 إجمالي التفعيلات الناجحة: {data['total_activations']}\n"
            f"📉 إجمالي المحاولات الفاشلة: {total_failed}\n"
            f"📊 **نسبة النجاح:** {success_rate:.2f}%"
        )
        
        if update.message:
            await update.message.reply_text(stats_msg, parse_mode="Markdown")
        elif update.callback_query:
            await update.callback_query.message.reply_text(stats_msg, parse_mode="Markdown")
        else:
            await context.bot.send_message(chat_id=update.effective_user.id, text=stats_msg, parse_mode="Markdown")
            
    except Exception as e:
        logging.error(f"❌ خطأ في stats_command: {e}")
        try:
            if update.callback_query:
                await update.callback_query.message.reply_text("⚠️ حدث خطأ في جلب الإحصائيات")
            elif update.message:
                await update.message.reply_text("⚠️ حدث خطأ في جلب الإحصائيات")
        except:
            pass

async def about_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        about_msg = (
            "ℹ️ **معلومات عن البوت** ℹ️\n\n"
            "✨ بوت احترافي لتفعيل 1 غيغا مجاني من جيزي يومياً.\n\n"
            "🔹 **المميزات:**\n"
            "• خصوصية تامة للرقم\n"
            "• سرعة عالية واستقرار\n"
            "• إحصائيات دقيقة\n"
            "• نظام إحالات بجوائز قيمة 🏆\n"
            "• دعم فني متواصل\n\n"
            "📢 **للاستفسار:** @ahmaeedinfo\n"
            "🌟 **تم البرمجة بإتقان** 🌟"
        )
        await query.edit_message_text(
            about_msg,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 رجوع", callback_data="back_to_start")]])
        )
    except Exception as e:
        logging.error(f"❌ خطأ في about_callback: {e}")

async def back_to_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        not_joined = await get_not_joined(context.bot, user_id)
        
        if not_joined:
            await query.edit_message_text(
                "🔔 **لازم تشترك في القنوات أولاً** 🔔",
                reply_markup=sub_keyboard(not_joined)
            )
            return
            
        await query.edit_message_text(
            "🎯 **مرحباً بعودتك يا بطل!** 🎯\n\n"
            "📲 أرسل رقم هاتفك الآن للتفعيل (يبدأ بـ 07، مثال: `07xxxxxxxx`)",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏆 المتصدرين", callback_data="leaderboard")],
                [InlineKeyboardButton("ℹ️ معلومات", callback_data="about")],
                [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats")],
                [InlineKeyboardButton("👥 رابط الإحالة", callback_data="my_referrals")]
            ])
        )
        context.user_data["conversation_state"] = STEP_SENDER
        
    except Exception as e:
        logging.error(f"❌ خطأ في back_to_start: {e}")

async def reactivate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        data = await load_data_async()
        user_data = data["users"].get(str(user_id), {})
        token = user_data.get("token")
        expiry = user_data.get("token_expiry", 0)
        phone = user_data.get("phone")
        
        if not phone:
            await query.edit_message_text("❌ لا يوجد رقم مسجل\nاكتب /start للبدء", parse_mode="Markdown")
            return
            
        if token and time.time() < expiry:
            await query.edit_message_text("⏳ **جاري إعادة التفعيل...** ⏳", parse_mode="Markdown")
            await single_attempt(update, context, token, phone, user_id)
        else:
            await query.edit_message_text("⌛ **الجلسة انتهت**\nاكتب /start للحصول على رمز جديد", parse_mode="Markdown")
            
    except Exception as e:
        logging.error(f"❌ خطأ في reactivate_callback: {e}")
        await query.answer("⚠️ حدث خطأ", show_alert=True)

async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        await stats_command(update, context)
    except Exception as e:
        logging.error(f"❌ خطأ في stats_callback: {e}")

async def leaderboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        await leaderboard_command(update, context)
    except Exception as e:
        logging.error(f"❌ خطأ في leaderboard_callback: {e}")

async def my_referrals_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        await my_referrals(update, context)
    except Exception as e:
        logging.error(f"❌ خطأ في my_referrals_callback: {e}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory().percent
        uptime = time.time() - psutil.boot_time()
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        
        status_msg = (
            f"⚙️ **حالة الخادم** ⚙️\n\n"
            f"🖥️ المعالج: {cpu}%\n"
            f"🧠 الذاكرة: {mem}%\n"
            f"⏰ مدة التشغيل: {hours} ساعة و {minutes} دقيقة"
        )
        await update.message.reply_text(status_msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(f"❌ خطأ في status_command: {e}")
        await update.message.reply_text("⚠️ حدث خطأ في جلب المعلومات")

# -------------------- معالج حذف الرسائل التي تحتوي أرقام هواتف --------------------

async def delete_phone_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if context.user_data.get("conversation_state") == STEP_SENDER:
        return
    if is_phone_number(update.message.text):
        try:
            await update.message.delete()
        except Exception as e:
            logging.error(f"حذف رسالة: {e}")

# -------------------- معالج الأخطاء --------------------

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.error(f"❌ Exception: {context.error}")
    try:
        if update and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ عذراً، حدث خطأ غير متوقع. الرجاء المحاولة مرة أخرى."
            )
    except:
        pass

async def heartbeat(context):
    logging.info("❤️ BOT WORKING...")

async def post_init(app):
    logging.info("✅ تم تهيئة البوت بنجاح")
    # بدء الوظيفة الدورية لفحص الإحالات كل ساعة
    job_queue = app.job_queue
    job_queue.run_repeating(check_referrals_job, interval=3600, first=60)

async def post_shutdown(app):
    logging.info("✅ تم إيقاف البوت بنجاح")

# -------------------- التشغيل الرئيسي --------------------

def main():
    try:
        app = Application.builder() \
            .token(BOT_TOKEN) \
            .concurrent_updates(True) \
            .post_init(post_init) \
            .post_shutdown(post_shutdown) \
            .build()

        conv = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                STEP_SENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sender)],
                STEP_OTP:    [MessageHandler(filters.TEXT & ~filters.COMMAND, verify_otp)],
            },
            fallbacks=[CallbackQueryHandler(cancel_callback, pattern="^cancel$")],
            allow_reentry=True
        )
        app.add_handler(conv)

        app.add_handler(CallbackQueryHandler(check_sub, pattern="^check_sub$"))
        app.add_handler(CallbackQueryHandler(about_callback, pattern="^about$"))
        app.add_handler(CallbackQueryHandler(back_to_start, pattern="^back_to_start$"))
        app.add_handler(CallbackQueryHandler(reactivate_callback, pattern="^reactivate$"))
        app.add_handler(CallbackQueryHandler(stats_callback, pattern="^stats$"))
        app.add_handler(CallbackQueryHandler(leaderboard_callback, pattern="^leaderboard$"))
        app.add_handler(CallbackQueryHandler(my_referrals_callback, pattern="^my_referrals$"))
        app.add_handler(CallbackQueryHandler(cancel_callback, pattern="^cancel$"))

        app.add_handler(CommandHandler("status", status_command))
        app.add_handler(CommandHandler("stats", stats_command))
        app.add_handler(CommandHandler("leaderboard", leaderboard_command))
        app.add_handler(CommandHandler("myref", my_referrals))

        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, delete_phone_messages),
            group=1
        )

        app.add_error_handler(error_handler)
        app.job_queue.run_repeating(heartbeat, interval=60, first=10)

        logging.info("🚀 Bot Started Successfully...")
        app.run_polling(drop_pending_updates=True)

    except Exception as e:
        logging.error(f"❌ خطأ في تشغيل البوت: {e}")

if __name__ == "__main__":
    main()