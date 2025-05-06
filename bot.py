import telebot
from telebot import types
from config import TOKEN, AGREEMENT_URL, PRIVACY_URL, ADMIN_ID
from database import users
from utils import calculate_distance
from datetime import datetime, timedelta
import time
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=4)
user_data = {}

GENDERS = ["Мужчина", "Женщина"]
TARGETS = ["Мужчину", "Женщину", "Не важно"]
HOBBIES = [
    "🎵 Музыка", "🎮 Игры", "📚 Чтение", "🏃 Спорт", "🎨 Искусство",
    "🍳 Кулинария", "✈️ Путешествия", "🎥 Кино", "🐶 Животные",
    "💻 Программирование", "🌳 Природа", "🏋️ Фитнес", "📷 Фото"
]


def safe_bot_send_message(chat_id, text, **kwargs):
    """Безопасная отправка сообщения с обработкой ошибок"""
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        logger.error(f"Error sending message to {chat_id}: {str(e)}")
        time.sleep(1)
        try:
            return bot.send_message(chat_id, text, **kwargs)
        except Exception as e:
            logger.error(f"Second attempt failed for {chat_id}: {str(e)}")
            return None


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


@bot.message_handler(commands=['start'])
def start(msg):
    user_data[msg.chat.id] = {}
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(*GENDERS)
    safe_bot_send_message(msg.chat.id, "Привет! Ваш пол?", reply_markup=markup)


@bot.message_handler(func=lambda m: m.text in GENDERS)
def ask_name(msg):
    user_data[msg.chat.id]["gender"] = msg.text
    markup = types.ReplyKeyboardRemove()
    safe_bot_send_message(msg.chat.id, "Как вас зовут?", reply_markup=markup)


@bot.message_handler(
    func=lambda m: "gender" in user_data.get(m.chat.id, {}) and "name" not in user_data.get(m.chat.id, {}))
def save_name_and_ask_target(msg):
    if len(msg.text.strip()) < 2:
        safe_bot_send_message(msg.chat.id, "Имя слишком короткое. Введите имя еще раз:")
        return

    user_data[msg.chat.id]["name"] = msg.text.strip()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(*TARGETS)
    safe_bot_send_message(msg.chat.id, f"{msg.text.strip()}, кого вы ищете?", reply_markup=markup)


@bot.message_handler(func=lambda m: m.text in TARGETS)
def ask_photo(msg):
    user_data[msg.chat.id]["looking_for"] = msg.text
    safe_bot_send_message(msg.chat.id, "Пожалуйста, отправьте своё фото")


@bot.message_handler(content_types=['photo'])
def ask_age(msg):
    photo_id = msg.photo[-1].file_id
    user_data[msg.chat.id]["photo"] = photo_id
    safe_bot_send_message(msg.chat.id, "Сколько вам лет? (от 18 до 99)")


@bot.message_handler(func=lambda m: m.text.isdigit() and 18 <= int(m.text) <= 99)
def ask_height(msg):
    user_data[msg.chat.id]["age"] = int(msg.text)
    safe_bot_send_message(msg.chat.id, "Ваш рост в см?")


@bot.message_handler(func=lambda m: m.text.isdigit() and 100 <= int(m.text) <= 250)
def ask_bio(msg):
    user_data[msg.chat.id]["height"] = int(msg.text)
    safe_bot_send_message(msg.chat.id, "Расскажите о себе:")


@bot.message_handler(
    func=lambda m: "height" in user_data.get(m.chat.id, {}) and "bio" not in user_data.get(m.chat.id, {}))
def save_bio_and_ask_hobbies(msg):
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


@bot.message_handler(func=lambda m: m.text in HOBBIES and "height" in user_data.get(m.chat.id, {}))
def handle_hobby_selection(msg):
    chat_id = msg.chat.id
    if "hobbies" not in user_data[chat_id]:
        user_data[chat_id]["hobbies"] = []

    if msg.text not in user_data[chat_id]["hobbies"]:
        user_data[chat_id]["hobbies"].append(msg.text)
    else:
        user_data[chat_id]["hobbies"].remove(msg.text)

    ask_hobbies(chat_id)


@bot.message_handler(func=lambda m: m.text == "✅ Готово" and "height" in user_data.get(m.chat.id, {}))
def check_hobbies_and_ask_location(msg):
    chat_id = msg.chat.id
    if not user_data.get(chat_id, {}).get("hobbies"):
        safe_bot_send_message(chat_id, "Пожалуйста, выберите хотя бы одно увлечение!")
        ask_hobbies(chat_id)
        return

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
    user_data[msg.chat.id]["verified"] = False
    save_profile_after_verification(msg.chat.id)


@bot.message_handler(content_types=['contact'])
def handle_contact(msg):
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
                    "viewed": []
                }
            },
            upsert=True
        )

        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("🔍 Начать поиск", "❤️ Мои совпадения", "✏️ Редактировать профиль")

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

        del user_data[chat_id]
    except Exception as e:
        logger.error(f"Error saving profile for {chat_id}: {str(e)}")
        safe_bot_send_message(chat_id, "Произошла ошибка при сохранении профиля. Попробуйте еще раз.")


@bot.message_handler(commands=['accept'])
def save_profile(msg):
    safe_bot_send_message(msg.chat.id, "Пожалуйста, завершите процесс регистрации.")


@bot.message_handler(func=lambda m: m.text == "🔍 Начать поиск")
def start_search(msg):
    try:
        me = users.find_one({"_id": msg.chat.id})
        if not me:
            safe_bot_send_message(msg.chat.id, "Сначала зарегистрируйтесь с /start")
            return

        eight_hours_ago = datetime.now() - timedelta(hours=8)

        query = {
            "_id": {"$ne": msg.chat.id},
            "$or": [
                {"_id": {"$nin": me.get("viewed", [])}},
                {"last_viewed": {"$lt": eight_hours_ago}}
            ]
        }

        if me.get("looking_for") != "Не важно":
            query["gender"] = "Мужчина" if me["looking_for"] == "Мужчину" else "Женщина"

        all_profiles = list(users.find(query))
        my_location = get_user_location(me)

        # Сортируем профили
        nearby = []
        for profile in all_profiles:
            profile_location = get_user_location(profile)
            if my_location and profile_location:
                try:
                    distance = calculate_distance(my_location, profile_location)
                except Exception as e:
                    logger.error(f"Error calculating distance: {e}")
                    distance = float('inf')
            else:
                distance = float('inf')

            nearby.append((profile, distance))

        # Сортируем сначала по верификации, затем по расстоянию
        nearby.sort(key=lambda x: (-int(x[0].get("verified", False)), x[1]))
        nearby = nearby[:50]  # Ограничиваем количество результатов

        if not nearby:
            safe_bot_send_message(msg.chat.id, "Пока нет новых анкет поблизости. Попробуйте позже.")
            return

        user_data[msg.chat.id] = {
            "search_results": [p[0]["_id"] for p in nearby],
            "current_index": 0
        }
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

        if not profile:
            safe_bot_send_message(chat_id, "Ошибка загрузки анкеты.")
            return

        users.update_one(
            {"_id": chat_id},
            {
                "$addToSet": {"viewed": profile_id},
                "$set": {f"viewed_times.{profile_id}": datetime.now()}
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
        bot.send_message(
            ADMIN_ID,
            f"⚠️ Жалоба на пользователя ID: {target_id}\n"
            f"От: @{call.from_user.username or call.from_user.id}\n"
            f"Имя: {call.from_user.first_name or 'не указано'}"
        )
        bot.answer_callback_query(call.id, "Жалоба отправлена. Спасибо!")
    except Exception as e:
        logger.error(f"Error sending report: {str(e)}")
        bot.answer_callback_query(call.id, "Ошибка отправки жалобы")
    finally:
        show_next_profile(call.message.chat.id)


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
    try:
        user = users.find_one({"_id": msg.chat.id})
        if not user:
            safe_bot_send_message(msg.chat.id, "Сначала зарегистрируйтесь с /start")
            return

        matches = users.find({
            "_id": {"$in": user.get("liked_by", [])},
            "liked": msg.chat.id
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
    ask_phone_verification(msg.chat.id)


def process_new_name(msg):
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
    try:
        users.update_one({"_id": msg.chat.id}, {"$set": {"bio": msg.text}})
        safe_bot_send_message(msg.chat.id, "Описание обновлено!")
    except Exception as e:
        logger.error(f"Error updating bio for {msg.chat.id}: {str(e)}")
        safe_bot_send_message(msg.chat.id, "Произошла ошибка при обновлении описания.")


@bot.message_handler(func=lambda m: m.text == "◀️ Назад")
def back_to_main(msg):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔍 Начать поиск", "❤️ Мои совпадения", "✏️ Редактировать профиль")
    safe_bot_send_message(msg.chat.id, "Главное меню:", reply_markup=markup)


def run_bot():
    while True:
        try:
            logger.info("Starting bot polling...")
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            logger.error(f"Bot crashed with error: {str(e)}")
            logger.info("Restarting bot in 10 seconds...")
            time.sleep(10)


if __name__ == "__main__":
    logger.info("Бот запущен...")
    run_bot()