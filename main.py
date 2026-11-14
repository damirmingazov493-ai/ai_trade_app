import asyncio
import os
import random
import time  # <--- ВОТ ЭТО ДОБАВИЛОСЬ (для сброса кэша)
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ВЕБ-СЕРВЕР ---

async def handle_index(request):
    return web.FileResponse('./index.html')

async def handle_analyze(request):
    await asyncio.sleep(1.5) 
    verdicts = [
        "📈 <b>Бычий тренд.</b> Объемы растут. Рекомендация: <b>LONG</b>.",
        "📉 <b>Медвежий сценарий.</b> Цена тестирует поддержку. Рекомендация: <b>SHORT</b>.",
        "⚖️ <b>Боковик.</b> Рынок консолидируется. Лучше подождать.",
        "🚀 <b>Паттерн 'Чашка с ручкой'.</b> Цель: $68,000. Рекомендация: <b>LONG</b>."
    ]
    fake_ai_response = random.choice(verdicts)
    return web.json_response({"analysis": fake_ai_response})

async def handle_trade(request):
    data = await request.json()
    trade_type = data.get('type')
    price = data.get('price')
    print(f"🔔 Сделка: {trade_type} по цене ${price}")
    return web.json_response({
        "status": "success", 
        "message": f"✅ Успешно открыта сделка {trade_type} по цене ${price}!"
    })

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_post('/api/analyze', handle_analyze)
    app.router.add_post('/api/trade', handle_trade)
    
    port = int(os.environ.get('PORT', 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Веб-сервер запущен на порту {port}")

# --- ТЕЛЕГРАМ БОТ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Берем ссылку и добавляем к ней текущее время (чтобы Telegram не кэшировал старую версию)
    base_url = os.getenv("WEBAPP_URL", "https://google.com")
    web_app_url = f"{base_url}?v={int(time.time())}"  # <--- ВОТ ЭТА МАГИЯ
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть Терминал", web_app=WebAppInfo(url=web_app_url))]
    ])
    
    await bot.send_message(
        chat_id=message.chat.id,
        text=f"Привет, {message.from_user.first_name}!\n\n"
             "Добро пожаловать в AI Trading Terminal. Нажми на кнопку ниже, чтобы открыть приложение.",
        reply_markup=keyboard
    )

# --- ЗАПУСК ---

async def main():
    await start_web_server()
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())