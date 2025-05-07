import telebot
from telebot import types
from config import TOKEN, AGREEMENT_URL, PRIVACY_URL, ADMIN_ID
from database import users, old_profiles
from utils import calculate_distance
from datetime import datetime, timedelta
import time
import logging
from collections import defaultdict

# Константы
MAX_AGE_DIFFERENCE = 10  # Максимальная разница в возрасте
MIN_HOBBY_MATCH = 0.3  # Минимальное совпадение интересов (0-1)
REQUEST_COOLDOWN = 1  # Секунды между запросами от одного пользователя

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=4)
user_data = {}
user_last_request = defaultdict(float)

GENDERS = ["Мужчина", "Женщина"]
TARGETS = ["Мужчину", "Женщину", "Не важно"]
HOBBIES = [
    "🎵 Музыка", "🎮 Игры", "📚 Чтение", "🏃 Спорт", "🎨 Искусство",
    "🍳 Кулинария", "✈️ Путешествия", "🎥 Кино", "🐶 Животные",
    "💻 Программирование", "🌳 Природа", "🏋️ Фитнес", "📷 Фото"
]
BANNED_WORDS = ["http", "www", ".com", "куплю", "продам", "деньги", "работа"]

def safe_bot_send_message(chat_id, text, **kwargs):
    """Безопасная отправка сообщения с обработкой ошибок"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return bot.send_message(chat_id, text, **kwargs)
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed for {chat_id}: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.error(f"Failed to send message to {chat_id} after {max_retries} attempts")
                return None

def validate_profile(profile):
    """Проверяет, что профиль содержит все необходимые данные"""
    required_fields = [
        'name', 'gender', 'age', 'height', 'bio',
        'hobbies', 'photo', 'location'
    ]
    return all(field in profile and profile[field] for field in required_fields)

def get_user_location(user):
    """Получаем координаты пользователя в правильном формате"""
    loc = user.get("location", {})
    if not loc:
        return None

    try:
        lat = float(loc.get("latitude", 0))
        lon = float(loc.get("longitude", 0))
        return (lat, lon)
    except (TypeError, ValueError):
        return None

def check_suspicious_profile(profile):
    """Проверяет профиль на подозрительные признаки"""
    suspicious = False
    reasons = []

    if not profile.get('name') or len(profile['name']) < 2:
        suspicious = True
        reasons.append("Слишком короткое имя")

    bio = profile.get('bio', '')
    if len(bio) > 500:
        suspicious = True
        reasons.append("Слишком длинное описание")

    for word in BANNED_WORDS:
        if word in bio.lower():
            suspicious = True
            reasons.append(f"Найдено запрещенное слово: {word}")
            break

    return suspicious, reasons

def compare_hobbies(hobbies1, hobbies2):
    """Сравнивает два списка увлечений и возвращает коэффициент совпадения"""
    if not hobbies1 or not hobbies2:
        return 0.0

    set1 = set(hobbies1)
    set2 = set(hobbies2)
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0

def rate_limit_check(chat_id):
    """Проверяет частоту запросов от пользователя"""
    current_time = time.time()
    if current_time - user_last_request[chat_id] < REQUEST_COOLDOWN:
        safe_bot_send_message(chat_id, "Пожалуйста, не так быстро! Подождите немного.")
        return False
    user_last_request[chat_id] = current_time
    return True

@bot.message_handler(commands=['start'])
def start(msg):
    if not rate_limit_check(msg.chat.id):
        return

    user_data[msg.chat.id] = {}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(*GENDERS)
    safe_bot_send_message(msg.chat.id, "Привет! Ваш пол?", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text in GENDERS)
def ask_name(msg):
    if not rate_limit_check(msg.chat.id):
        return

    if msg.chat.id not in user_data:
        user_data[msg.chat.id] = {}
    user_data[msg.chat.id]["gender"] = msg.text
    markup = types.ReplyKeyboardRemove()
    safe_bot_send_message(msg.chat.id, "Как вас зовут?", reply_markup=markup)

@bot.message_handler(
    func=lambda m: "gender" in user_data.get(m.chat.id, {}) and "name" not in user_data.get(m.chat.id, {}))
def save_name_and_ask_target(msg):
    if not rate_limit_check(msg.chat.id):
        return

    if len(msg.text.strip()) < 2:
        safe_bot_send_message(msg.chat.id, "Имя слишком короткое. Введите имя еще раз:")
        return

    user_data[msg.chat.id]["name"] = msg.text.strip()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(*TARGETS)
    safe_bot_send_message(msg.chat.id, f"{msg.text.strip()}, кого вы ищете?", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text in TARGETS)
def ask_photo(msg):
    if not rate_limit_check(msg.chat.id):
        return

    user_data[msg.chat.id]["looking_for"] = msg.text
    safe_bot_send_message(msg.chat.id, "Пожалуйста, отправьте своё фото")

@bot.message_handler(content_types=['photo'])
def ask_age(msg):
    if not rate_limit_check(msg.chat.id):
        return

    if not msg.photo:
        safe_bot_send_message(msg.chat.id, "Пожалуйста, отправьте фото.")
        return

    photo_id = msg.photo[-1].file_id
    if msg.chat.id not in user_data:
        user_data[msg.chat.id] = {}
    user_data[msg.chat.id]["photo"] = photo_id
    safe_bot_send_message(msg.chat.id, "Сколько вам лет? (от 18 до 99)")

@bot.message_handler(func=lambda m: m.text.isdigit() and 18 <= int(m.text) <= 99)
def ask_height(msg):
    if not rate_limit_check(msg.chat.id):
        return

    user_data[msg.chat.id]["age"] = int(msg.text)
    safe_bot_send_message(msg.chat.id, "Ваш рост в см?")

@bot.message_handler(func=lambda m: m.text.isdigit() and 100 <= int(m.text) <= 250)
def ask_bio(msg):
    if not rate_limit_check(msg.chat.id):
        return

    user_data[msg.chat.id]["height"] = int(msg.text)
    safe_bot_send_message(msg.chat.id, "Расскажите о себе:")

@bot.message_handler(
    func=lambda m: "height" in user_data.get(m.chat.id, {}) and "bio" not in user_data.get(m.chat.id, {}))
def save_bio_and_ask_hobbies(msg):
    if not rate_limit_check(msg.chat.id):
        return

    user_data[msg.chat.id]["bio"] = msg.text
    ask_hobbies(msg.chat.id)

def ask_hobbies(chat_id):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    buttons = [types.KeyboardButton(h) for h in HOBBIES]
    markup.add(*buttons)
    markup.add(types.KeyboardButton("✅ Готово"))

    selected_hobbies = user_data.get(chat_id, {}).get("hobbies", [])
    text = (
            "Выберите увлечения (можно несколько):\n\n" +
            "Выбрано: " + (", ".join(selected_hobbies) if selected_hobbies else "пока ничего") +
            "\n\nНажимайте по одному, затем '✅ Готово'"
    )

    safe_bot_send_message(chat_id, text, reply_markup=markup)

@bot.message_handler(func=lambda m: m.text in HOBBIES and ("height" in user_data.get(m.chat.id, {}) or user_data.get(m.chat.id, {}).get("editing")))
def handle_hobby_selection(msg):
    if not rate_limit_check(msg.chat.id):
        return

    chat_id = msg.chat.id
    if "hobbies" not in user_data[chat_id]:
        user_data[chat_id]["hobbies"] = []

    if msg.text not in user_data[chat_id]["hobbies"]:
        user_data[chat_id]["hobbies"].append(msg.text)
    else:
        user_data[chat_id]["hobbies"].remove(msg.text)

    ask_hobbies(chat_id)


@bot.message_handler(func=lambda m: m.text == "✅ Готово" and (
        "height" in user_data.get(m.chat.id, {}) or user_data.get(m.chat.id, {}).get("editing")))
def check_hobbies_and_ask_location(msg):
    if not rate_limit_check(msg.chat.id):
        return

    chat_id = msg.chat.id

    # Проверяем, что выбрано хотя бы одно увлечение
    if not user_data.get(chat_id, {}).get("hobbies"):
        safe_bot_send_message(chat_id, "Пожалуйста, выберите хотя бы одно увлечение!")
        ask_hobbies(chat_id)
        return

    if user_data[chat_id].get("editing"):
        # Режим редактирования - сохраняем увлечения и возвращаем в главное меню
        try:
            users.update_one(
                {"_id": chat_id},
                {"$set": {"hobbies": user_data[chat_id]["hobbies"]}}
            )
            safe_bot_send_message(chat_id, "Увлечения успешно обновлены!")
            del user_data[chat_id]["editing"]

            # Возвращаем в главное меню
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("🔍 Начать поиск", "❤️ Мои совпадения", "✏️ Редактировать профиль")
            safe_bot_send_message(chat_id, "Главное меню:", reply_markup=markup)
        except Exception as e:
            logger.error(f"Error updating hobbies for {chat_id}: {str(e)}")
            safe_bot_send_message(chat_id, "Произошла ошибка при обновлении увлечений.")
    else:
        # Режим регистрации - переходим к запросу локации
        ask_location(msg.chat.id)

def ask_location(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    location_button = types.KeyboardButton("📍 Отправить локацию", request_location=True)
    markup.add(location_button)
    safe_bot_send_message(
        chat_id,
        "Пожалуйста, поделитесь своей геолокацией, чтобы мы могли находить людей рядом с вами.",
        reply_markup=markup
    )

@bot.message_handler(content_types=['location'])
def handle_location(msg):
    if not rate_limit_check(msg.chat.id):
        return

    if msg.location:
        user_data[msg.chat.id]["location"] = {
            "latitude": msg.location.latitude,
            "longitude": msg.location.longitude
        }
        ask_phone_verification(msg.chat.id)
    else:
        safe_bot_send_message(msg.chat.id, "Не удалось получить вашу геопозицию. Попробуйте ещё раз.")
        ask_location(msg.chat.id)

def ask_phone_verification(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    phone_btn = types.KeyboardButton("📱 Отправить номер телефона", request_contact=True)
    skip_btn = types.KeyboardButton("🚫 Пропустить верификацию")
    markup.add(phone_btn, skip_btn)

    safe_bot_send_message(
        chat_id,
        "Верификация по номеру телефона дает вам синюю галочку и больше доверия от других пользователей.\n\n"
        "Вы можете:\n"
        "1. Нажать кнопку ниже, чтобы поделиться номером телефона\n"
        "2. Пропустить верификацию (но ваш профиль будет менее заметен)",
        reply_markup=markup
    )

@bot.message_handler(func=lambda m: m.text == "🚫 Пропустить верификацию")
def skip_verification(msg):
    if not rate_limit_check(msg.chat.id):
        return

    user_data[msg.chat.id]["verified"] = False
    save_profile_after_verification(msg.chat.id)

@bot.message_handler(content_types=['contact'])
def handle_contact(msg):
    if not rate_limit_check(msg.chat.id):
        return

    if msg.contact.user_id == msg.from_user.id:
        user_data[msg.chat.id]["phone"] = msg.contact.phone_number
        user_data[msg.chat.id]["verified"] = True
        save_profile_after_verification(msg.chat.id)
    else:
        safe_bot_send_message(
            msg.chat.id,
            "Пожалуйста, поделитесь своим собственным номером телефона."
        )

def save_profile_after_verification(chat_id):
    user_data[chat_id]["username"] = bot.get_chat(chat_id).username
    user_data[chat_id]["registered_at"] = datetime.now()

    try:
        users.update_one(
            {"_id": chat_id},
            {
                "$set": user_data[chat_id],
                "$setOnInsert": {
                    "liked": [],
                    "liked_by": [],
                    "viewed": [],
                    "reports": 0,
                    "banned": False
                }
            },
            upsert=True
        )

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("🔍 Начать поиск", "❤️ Мои совпадения", "✏️ Редактировать профиль")

        warning_text = (
            "⚠️ Помните! В интернете люди могут выдавать себя за других. "
            "Бот не запрашивает личные данные и не идентифицирует пользователей по документам.\n\n"
            f"Продолжая, вы принимаете [Пользовательское соглашение]({AGREEMENT_URL}) и "
            f"[Политику конфиденциальности]({PRIVACY_URL})."
        )

        if user_data[chat_id].get("verified", False):
            safe_bot_send_message(
                chat_id,
                "✅ Регистрация и верификация завершены! Теперь у вас есть синяя галочка ✅",
                reply_markup=markup
            )
        else:
            safe_bot_send_message(
                chat_id,
                "✅ Регистрация завершена! Вы можете пройти верификацию позже в настройках профиля.",
                reply_markup=markup
            )

        safe_bot_send_message(
            chat_id,
            warning_text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

        del user_data[chat_id]
    except Exception as e:
        logger.error(f"Error saving profile for {chat_id}: {str(e)}")
        safe_bot_send_message(chat_id, "Произошла ошибка при сохранении профиля. Попробуйте еще раз.")


@bot.message_handler(func=lambda m: m.text == "🔍 Начать поиск")
def start_search(msg):
    if not rate_limit_check(msg.chat.id):
        return

    try:
        me = users.find_one({"_id": msg.chat.id})
        if not me:
            safe_bot_send_message(msg.chat.id, "Сначала зарегистрируйтесь с /start")
            return

        if not validate_profile(me):
            safe_bot_send_message(msg.chat.id, "Ваш профиль неполный. Пожалуйста, заполните все данные.")
            return

        # Время, после которого анкета снова показывается (8 часов)
        eight_hours_ago = datetime.now() - timedelta(hours=8)

        # Формируем запрос для поиска
        query = {
            "_id": {"$ne": msg.chat.id},  # Исключаем себя
            "banned": {"$ne": True},  # Исключаем заблокированных
            "deleted": {"$ne": True},  # Исключаем удаленных
            "$or": [  # Исключаем просмотренные или те, что просматривали давно
                {"_id": {"$nin": me.get("viewed", [])}},
                {"last_viewed": {"$lt": eight_hours_ago}}
            ]
        }

        # Если пользователь ищет конкретный пол
        if me.get("looking_for") != "Не важно":
            query["gender"] = "Женщина" if me["looking_for"] == "Женщину" else "Мужчина"

        # Получаем все подходящие анкеты
        all_profiles = list(users.find(query))

        # Получаем данные для фильтрации
        my_location = get_user_location(me)
        my_age = me.get("age", 0)
        my_hobbies = me.get("hobbies", [])

        filtered_profiles = []
        for profile in all_profiles:
            # Пропускаем неполные анкеты
            if not validate_profile(profile):
                continue

            # Фильтр по возрасту
            profile_age = profile.get("age", 0)
            if abs(profile_age - my_age) > MAX_AGE_DIFFERENCE:
                continue

            # Фильтр по интересам
            profile_hobbies = profile.get("hobbies", [])
            hobby_match = compare_hobbies(my_hobbies, profile_hobbies)
            if hobby_match < MIN_HOBBY_MATCH:
                continue

            # Проверка на подозрительные анкеты
            suspicious, reasons = check_suspicious_profile(profile)
            if suspicious:
                logger.warning(f"Suspicious profile {profile['_id']}: {', '.join(reasons)}")
                users.update_one({"_id": profile["_id"]}, {"$set": {"banned": True}})
                continue

            # Рассчитываем расстояние между пользователями
            profile_location = get_user_location(profile)
            if my_location and profile_location:
                try:
                    distance = calculate_distance(my_location, profile_location)
                except Exception as e:
                    logger.error(f"Error calculating distance: {e}")
                    distance = float('inf')
            else:
                distance = float('inf')

            # Рассчитываем рейтинг анкеты
            rating = (
                    int(profile.get("verified", False)) * 100 +  # Верифицированные выше
                    hobby_match * 10 +  # Совпадение интересов
                    1 / (distance + 1)  # Близкие анкеты выше
            )
            filtered_profiles.append((profile, rating))

        # Сортируем по рейтингу и берем топ-50
        filtered_profiles.sort(key=lambda x: -x[1])
        filtered_profiles = filtered_profiles[:50]

        if not filtered_profiles:
            safe_bot_send_message(msg.chat.id, "Пока нет подходящих анкет. Попробуйте позже.")
            return

        # Сохраняем результаты поиска
        user_data[msg.chat.id] = {
            "search_results": [p[0]["_id"] for p in filtered_profiles],
            "current_index": 0
        }

        # Показываем первую анкету
        show_profile(msg.chat.id, 0)
    except Exception as e:
        logger.error(f"Error in start_search for {msg.chat.id}: {str(e)}")
        safe_bot_send_message(msg.chat.id, "Произошла ошибка при поиске. Попробуйте позже.")

def show_profile(chat_id, index):
    try:
        search_data = user_data.get(chat_id, {}).get("search_results", [])
        if not search_data or index >= len(search_data):
            safe_bot_send_message(chat_id, "Новые анкеты закончились. Попробуйте позже.")
            return

        profile_id = search_data[index]
        profile = users.find_one({"_id": profile_id})

        if not profile or not validate_profile(profile):
            safe_bot_send_message(chat_id, "Ошибка загрузки анкеты.")
            return

        users.update_one(
            {"_id": chat_id},
            {
                "$addToSet": {"viewed": profile_id},
                "$set": {"last_viewed": datetime.now()}
            }
        )

        verified_badge = " ✅" if profile.get("verified", False) else ""
        text = (
            f"{profile.get('name', 'Без имени')}{verified_badge}, {profile['gender']}, {profile['age']} лет, {profile['height']}см\n"
            f"Интересы: {', '.join(profile.get('hobbies', []))}\n"
            f"О себе: {profile.get('bio', '')}"
        )

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("👍", callback_data=f"like_{profile_id}"),
            types.InlineKeyboardButton("👎", callback_data=f"dislike_{profile_id}"),
            types.InlineKeyboardButton("⚠️ Пожаловаться", callback_data=f"report_{profile_id}")
        )

        try:
            bot.send_photo(chat_id, profile['photo'], caption=text, reply_markup=markup)
        except Exception as e:
            logger.error(f"Error sending photo to {chat_id}: {str(e)}")
            safe_bot_send_message(chat_id, text, reply_markup=markup)
    except Exception as e:
        logger.error(f"Error showing profile to {chat_id}: {str(e)}")
        safe_bot_send_message(chat_id, "Произошла ошибка при загрузке анкеты.")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    try:
        if not rate_limit_check(call.message.chat.id):
            return

        chat_id = call.message.chat.id
        if call.data.startswith('like_'):
            handle_like(call)
        elif call.data.startswith('dislike_'):
            handle_dislike(call)
        elif call.data.startswith('report_'):
            handle_report(call)
    except Exception as e:
        logger.error(f"Error handling callback: {str(e)}")
        try:
            bot.answer_callback_query(call.id, "Произошла ошибка. Попробуйте еще раз.")
        except:
            pass

def handle_like(call):
    chat_id = call.message.chat.id
    target_id = int(call.data.split('_')[1])

    try:
        user = users.find_one({"_id": chat_id})
        if target_id in user.get("liked", []):
            bot.answer_callback_query(call.id, "Вы уже лайкали этого пользователя")
            show_next_profile(chat_id)
            return

        users.update_one(
            {"_id": target_id},
            {"$addToSet": {"liked_by": chat_id}}
        )

        users.update_one(
            {"_id": chat_id},
            {"$addToSet": {"liked": target_id}}
        )

        target = users.find_one({"_id": target_id})
        if target and chat_id in target.get("liked", []):
            try:
                bot.send_message(
                    chat_id,
                    f"🎉 У вас взаимная симпатия с {target.get('name', 'пользователем')}!\n"
                    f"Напишите ему: @{target.get('username', 'нет username')}"
                )
                bot.send_message(
                    target_id,
                    f"🎉 У вас взаимная симпатия с {call.from_user.first_name or 'пользователем'}!\n"
                    f"Напишите ему: @{call.from_user.username or 'нет username'}"
                )
            except Exception as e:
                logger.error(f"Error sending match notification: {str(e)}")

        bot.answer_callback_query(call.id, "Лайк отправлен!")
        show_next_profile(chat_id)
    except Exception as e:
        logger.error(f"Error in handle_like: {str(e)}")
        bot.answer_callback_query(call.id, "Ошибка при отправке лайка")

def handle_dislike(call):
    chat_id = call.message.chat.id
    try:
        bot.answer_callback_query(call.id, "Пропускаем...")
        show_next_profile(chat_id)
    except Exception as e:
        logger.error(f"Error in handle_dislike: {str(e)}")

def handle_report(call):
    target_id = int(call.data.split('_')[1])
    try:
        users.update_one(
            {"_id": target_id},
            {"$inc": {"reports": 1}}
        )

        user = users.find_one({"_id": target_id})
        if user.get("reports", 0) >= 3:
            users.update_one(
                {"_id": target_id},
                {"$set": {"banned": True}}
            )
            bot.send_message(
                ADMIN_ID,
                f"Профиль {target_id} автоматически заблокирован из-за 3 жалоб"
            )
    except Exception as e:
        logger.error(f"Error processing report: {str(e)}")

def show_next_profile(chat_id):
    try:
        search_data = user_data.get(chat_id, {}).get("search_results", [])
        current_index = user_data.get(chat_id, {}).get("current_index", 0) + 1

        if current_index >= len(search_data):
            safe_bot_send_message(chat_id, "Новые анкеты закончились. Попробуйте позже.")
            return

        user_data[chat_id]["current_index"] = current_index
        show_profile(chat_id, current_index)
    except Exception as e:
        logger.error(f"Error in show_next_profile for {chat_id}: {str(e)}")
        safe_bot_send_message(chat_id, "Произошла ошибка при загрузке следующей анкеты.")

@bot.message_handler(func=lambda m: m.text == "❤️ Мои совпадения")
def show_matches(msg):
    if not rate_limit_check(msg.chat.id):
        return

    try:
        user = users.find_one({"_id": msg.chat.id})
        if not user:
            safe_bot_send_message(msg.chat.id, "Сначала зарегистрируйтесь с /start")
            return

        matches = users.find({
            "_id": {"$in": user.get("liked_by", [])},
            "liked": msg.chat.id,
            "banned": {"$ne": True},
            "deleted": {"$ne": True}
        })

        matches_list = list(matches)
        if not matches_list:
            safe_bot_send_message(msg.chat.id, "У вас пока нет взаимных симпатий.")
            return

        for match in matches_list:
            try:
                verified_badge = " ✅" if match.get("verified", False) else ""

                text = (
                    f"💕 Взаимная симпатия!\n"
                    f"{match.get('name', 'Без имени')}{verified_badge}, {match['gender']}, {match['age']} лет\n"
                    f"Интересы: {', '.join(match.get('hobbies', []))}\n\n"
                    f"Напишите: @{match.get('username', 'пользователь не указал username')}"
                )
                bot.send_photo(msg.chat.id, match['photo'], caption=text)
            except Exception as e:
                logger.error(f"Error showing match to {msg.chat.id}: {str(e)}")
                safe_bot_send_message(msg.chat.id, text)
    except Exception as e:
        logger.error(f"Error in show_matches for {msg.chat.id}: {str(e)}")
        safe_bot_send_message(msg.chat.id, "Произошла ошибка при загрузке совпадений.")

@bot.message_handler(func=lambda m: m.text == "✏️ Редактировать профиль")
def edit_profile(msg):
    if not rate_limit_check(msg.chat.id):
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    items = [
        "✏️ Изменить имя",
        "✏️ Изменить фото",
        "✏️ Изменить описание",
        "✏️ Изменить увлечения"
    ]

    user = users.find_one({"_id": msg.chat.id})
    if not user.get("verified", False):
        items.append("📱 Пройти верификацию")

    items.append("◀️ Назад")
    markup.add(*items)

    safe_bot_send_message(msg.chat.id, "Что вы хотите изменить?", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text.startswith("✏️ Изменить"))
def handle_edit_choice(msg):
    if not rate_limit_check(msg.chat.id):
        return

    if msg.text == "✏️ Изменить имя":
        safe_bot_send_message(msg.chat.id, "Введите новое имя:")
        bot.register_next_step_handler(msg, process_new_name)
    elif msg.text == "✏️ Изменить фото":
        safe_bot_send_message(msg.chat.id, "Отправьте новое фото")
        bot.register_next_step_handler(msg, process_new_photo)
    elif msg.text == "✏️ Изменить описание":
        safe_bot_send_message(msg.chat.id, "Введите новое описание:")
        bot.register_next_step_handler(msg, process_new_bio)
    elif msg.text == "✏️ Изменить увлечения":
        user_data[msg.chat.id] = {"editing": True}
        ask_hobbies(msg.chat.id)

@bot.message_handler(func=lambda m: m.text == "📱 Пройти верификацию")
def request_verification(msg):
    if not rate_limit_check(msg.chat.id):
        return

    ask_phone_verification(msg.chat.id)

def process_new_name(msg):
    if not rate_limit_check(msg.chat.id):
        return

    if len(msg.text.strip()) < 2:
        safe_bot_send_message(msg.chat.id, "Имя слишком короткое. Введите имя еще раз:")
        bot.register_next_step_handler(msg, process_new_name)
        return

    try:
        users.update_one({"_id": msg.chat.id}, {"$set": {"name": msg.text.strip()}})
        safe_bot_send_message(msg.chat.id, "Имя обновлено!")
    except Exception as e:
        logger.error(f"Error updating name for {msg.chat.id}: {str(e)}")
        safe_bot_send_message(msg.chat.id, "Произошла ошибка при обновлении имени.")

def process_new_photo(msg):
    if not rate_limit_check(msg.chat.id):
        return

    if not msg.photo:
        safe_bot_send_message(msg.chat.id, "Пожалуйста, отправьте фото.")
        return

    try:
        photo_id = msg.photo[-1].file_id
        users.update_one({"_id": msg.chat.id}, {"$set": {"photo": photo_id}})
        safe_bot_send_message(msg.chat.id, "Фото обновлено!")
    except Exception as e:
        logger.error(f"Error updating photo for {msg.chat.id}: {str(e)}")
        safe_bot_send_message(msg.chat.id, "Произошла ошибка при обновлении фото.")

def process_new_bio(msg):
    if not rate_limit_check(msg.chat.id):
        return

    try:
        users.update_one({"_id": msg.chat.id}, {"$set": {"bio": msg.text}})
        safe_bot_send_message(msg.chat.id, "Описание обновлено!")
    except Exception as e:
        logger.error(f"Error updating bio for {msg.chat.id}: {str(e)}")
        safe_bot_send_message(msg.chat.id, "Произошла ошибка при обновлении описания.")

@bot.message_handler(func=lambda m: m.text == "◀️ Назад")
def back_to_main(msg):
    if not rate_limit_check(msg.chat.id):
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔍 Начать поиск", "❤️ Мои совпадения", "✏️ Редактировать профиль")
    safe_bot_send_message(msg.chat.id, "Главное меню:", reply_markup=markup)

@bot.message_handler(commands=['deletemyprofile'])
def delete_profile(msg):
    if not rate_limit_check(msg.chat.id):
        return

    try:
        user = users.find_one({"_id": msg.chat.id})
        if not user:
            safe_bot_send_message(msg.chat.id, "Профиль не найден.")
            return

        old_profiles.insert_one(user)

        users.update_one(
            {"_id": msg.chat.id},
            {
                "$set": {
                    "deleted": True,
                    "deleted_at": datetime.now()
                }
            }
        )

        safe_bot_send_message(msg.chat.id, "Ваш профиль был удален. Спасибо, что были с нами!")
    except Exception as e:
        logger.error(f"Error deleting profile {msg.chat.id}: {str(e)}")
        safe_bot_send_message(msg.chat.id, "Произошла ошибка при удалении профиля.")

@bot.message_handler(func=lambda m: True)
def handle_unexpected_messages(msg):
    if not rate_limit_check(msg.chat.id):
        return

    if msg.chat.id in user_data:
        safe_bot_send_message(msg.chat.id, "Пожалуйста, следуйте инструкциям для завершения регистрации.")
    else:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("🔍 Начать поиск", "❤️ Мои совпадения", "✏️ Редактировать профиль")
        safe_bot_send_message(msg.chat.id, "Выберите действие из меню:", reply_markup=markup)

def run_bot():
    while True:
        try:
            logger.info("Starting bot polling...")
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=60,
                restart_on_change=True,
                skip_pending=True
            )
        except Exception as e:
            logger.error(f"Bot crashed with error: {str(e)}")
            logger.info("Restarting bot in 30 seconds...")
            time.sleep(30)

if __name__ == "__main__":
    logger.info("Бот запущен...")
    run_bot()