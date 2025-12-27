import asyncio
import json
import os
import re
from datetime import datetime, time, timedelta

from aiogram import Bot, Dispatcher, types

# ================== НАСТРОЙКИ ==================

TOKEN = "8282357462:AAF4-jmyBlx8lz8T_Q5_krf6KwF7k4Nrf-4"

SHIFT_CHAT_ID = -1002902485640      # ID рабочего чата
SHIFT_THREAD_ID = 2                # ID темы «Смены»

ADMIN_TAGS = "@danysamokhvalov @angelacher"

# 🔹 ВСЕ ТОЧКИ В ОДНОМ ФОРМАТЕ
RAW_POINTS = {
    "Ленина": time(9, 0),
    "Плазма": time(10, 0),
    "Буркова": time(10, 0),
    "Вокзал": time(8, 0),
    "Форум": time(10, 0),
    "Елан": time(10, 0),
    "Мурмаши": time(10, 0),
    "Волна": time(10, 0),
}

CONTROL_DELTA = timedelta(minutes=10)

ACTIVE_FILE = "active_shifts.json"
PENDING_FILE = "pending_geo.json"
LOG_FILE = "shifts_log.csv"
ALERT_FILE = "alerts_sent.json"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ================== УТИЛИТЫ ==================

def norm(text: str) -> str:
    return re.sub(r'[^а-яa-z0-9 ]', '', text.lower()).strip()

POINTS = {
    norm(name): {"name": name, "open": open_time}
    for name, open_time in RAW_POINTS.items()
}

def load(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except:
            return {}

def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def round_time(dt: datetime) -> datetime:
    m = dt.minute
    if m >= 45:
        return dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    elif m >= 15:
        return dt.replace(minute=30, second=0, microsecond=0)
    else:
        return dt.replace(minute=0, second=0, microsecond=0)

def hours_between(a, b):
    return round((b - a).total_seconds() / 3600, 2)

def log_shift(row):
    exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", encoding="utf-8-sig") as f:
        if not exists:
            f.write("Дата,Имя,Точка,Начало,Конец,Часы,Опоздание,Комментарий\n")
        f.write(",".join(row) + "\n")

# ================== ГЕО ==================

@dp.message(lambda m: m.location is not None)
async def geo_handler(message: types.Message):
    if message.chat.id != SHIFT_CHAT_ID or message.message_thread_id != SHIFT_THREAD_ID:
        return

    user = str(message.from_user.id)

    pending = load(PENDING_FILE)
    pending[user] = {
        "time": datetime.now().isoformat(),
        "name": message.from_user.full_name
    }
    save(PENDING_FILE, pending)

    await message.answer("📍 Гео принято")

# ================== ТЕКСТ / ПОДПИСЬ ==================

@dp.message()
async def text_handler(message: types.Message):
    if message.chat.id != SHIFT_CHAT_ID or message.message_thread_id != SHIFT_THREAD_ID:
        return

    user = str(message.from_user.id)
    text = message.text or message.caption
    if not text:
        return

    clean = norm(text)

    pending = load(PENDING_FILE)
    active = load(ACTIVE_FILE)

    if user not in pending:
        await message.answer("⚠ Сначала отправьте геопозицию")
        return

    geo_time_raw = datetime.fromisoformat(pending[user]["time"])
    geo_time = round_time(geo_time_raw)
    name = pending[user]["name"]

    # ===== ОТКРЫТИЕ =====
    if "смена открыта" in clean and user not in active:
        point_text = clean.replace("смена открыта", "").strip().title()

        if point_text not in POINTS:
            await message.answer(f"⚠ Точка «{point_text}» не найдена")
            return

        open_time = POINTS[point_text]
        control = datetime.combine(datetime.now().date(), open_time)
        late = "ДА" if geo_time_raw > control else "НЕТ"

        active[user] = {
            "name": name,
            "point": point_text,
            "start": geo_time.isoformat(),
            "late": late
        }

        save(ACTIVE_FILE, active)
        pending.pop(user)
        save(PENDING_FILE, pending)

        await message.answer(
            f"✅ Смена открыта\n"
            f"👤 {name}\n"
            f"🏪 {point_text}\n"
            f"Опоздание: {late}"
        )
        return


    # ===== ЗАКРЫТИЕ =====
    if "смена закрыта" in clean and user in active and user in pending:
        shift = active[user]
        start = datetime.fromisoformat(shift["start"])
        end = geo_time

        hours = hours_between(start, end)

        log_shift([
            start.strftime("%d.%m.%Y"),
            shift["name"],
            shift["point"],
            start.strftime("%H:%M"),
            end.strftime("%H:%M"),
            str(hours),
            shift["late"]
        ])

        active.pop(user)
        pending.pop(user)
        save(ACTIVE_FILE, active)
        save(PENDING_FILE, pending)

        await message.answer(
            f"✅ Смена закрыта\n"
            f"👤 {shift['name']}\n"
            f"🏪 {shift['point']}\n"
            f"⏱ {hours} ч"
        )

# ================== КОНТРОЛЬ ОПОЗДАНИЙ ==================

async def lateness_watcher():
    while True:
        now = datetime.now()
        active = load(ACTIVE_FILE)
        alerts = load(ALERT_FILE)

        for point, data in POINTS.items():
            open_time = data["open"]
            check_time = datetime.combine(now.date(), open_time) - CONTROL_DELTA
            key = f"{point}_{now.date()}"

            opened = any(s["point"] == data["name"] for s in active.values())
            if now.strftime("%H:%M") == check_time.strftime("%H:%M") and not opened and not alerts.get(key):
                await bot.send_message(
                    SHIFT_CHAT_ID,
                    f"❗ ТОЧКА НЕ ОТКРЫТА\n🏪 {data['name']}\n{ADMIN_TAGS}",
                    message_thread_id=SHIFT_THREAD_ID
                )
                alerts[key] = True
                save(ALERT_FILE, alerts)

        await asyncio.sleep(60)


# ---------- 📢 10:01 СТАТУС ----------
async def open_status_report():
    while True:
        now = datetime.now()
        if now.strftime("%H:%M") == "10:01":
            active = load(ACTIVE_FILE)
            opened = {v["point"] for v in active.values()}
            missing = [p["name"] for p in POINTS.values() if p["name"] not in opened]

            msg = "✅ Все магазины открыты" if not missing else "❌ Не открылись:\n" + "\n".join(missing)
            await bot.send_message(SHIFT_CHAT_ID, msg, message_thread_id=SHIFT_THREAD_ID)

        await asyncio.sleep(60)
        
# ---------- 🕑 АВТО-ЗАКРЫТИЕ ----------
async def auto_close_shifts():
    while True:
        now = datetime.now()
        if now.strftime("%H:%M") == "02:01":
            active = load(ACTIVE_FILE)
            for shift in active.values():
                start = datetime.fromisoformat(shift["start"])
                end = datetime.combine(start.date(), time(2, 0))
                hours = hours_between(start, end)

                log_shift([
                    start.strftime("%d.%m.%Y"),
                    shift["name"],
                    shift["point"],
                    start.strftime("%H:%M"),
                    "02:00",
                    str(hours),
                    shift["late"],
                    "Авто-закрытие"
                ])

            save(ACTIVE_FILE, {})

        await asyncio.sleep(60)

# ---------- ОЧИСТКА ЛОГОВ ----------
async def reset_alerts_daily():
    while True:
        now = datetime.now()
        if now.strftime("%H:%M") == "02:01":
            save(ALERT_FILE, {})  # полностью очищаем файл
            print("alerts_sent.json очищен")
        await asyncio.sleep(60)  # проверяем каждую минуту
# ================== ЗАПУСК ==================

async def main():
    asyncio.create_task(lateness_watcher())
    asyncio.create_task(open_status_report())
    asyncio.create_task(auto_close_shifts())
    asyncio.create_task(reset_alerts_daily())
    print("Бот смен запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
