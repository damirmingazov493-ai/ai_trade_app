import asyncio
import os
import random
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
    # Отдаем наш HTML файл
    return web.FileResponse('./index.html')

async def handle_analyze(request):
    # Имитация работы нейросети
    await asyncio.sleep(1.5) 
    verdicts = [
        "📈 <b>Бычий тренд.</b> Объемы растут. Рекомендация: <b>LONG</b>.",
        "📉 <b>Медвежий сценарий.</b> Цена тестирует поддержку. Рекомендация: <b>SHORT</b>.",
        "⚖️ <b>Боковик.</b> Рынок консолидируется. Лучше подождать.",
        "🚀 <b>Паттерн 'Чашка с ручкой'.</b> Цель: $68,000. Рекомендация: <b>LONG</b>."
    ]
    fake_ai_response = random.choice(verdicts)
    return web.json_response({"analysis": fake_ai_response})

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_post('/api/analyze', handle_analyze)
    
    port = int(os.environ.get('PORT', 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Веб-сервер запущен на порту {port}")

# --- БОТ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    # Railway передаст сюда ссылку на наш сайт через переменную окружения
    web_app_url = os.getenv("WEBAPP_URL", "https://google.com")
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Открыть Терминал", web_app=WebAppInfo(url=web_app_url))]
    ])
    
    await message.answer(
        f"Привет, {message.from_user.first_name}!\n\n"
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