# Парсер объявлений Avito

Проект предназначен для парсинга поисковой выдачи Avito. Информация объявлений кешируется в базу данных, новые и обновленные объявления отправляется в чат Telegram.

Бот в работе: [@avipars_bot](https://t.me/avipars_bot)

### Как установить

1. Python3 должен быть уже установлен.  

2. Используйте `pip` (или `pip3`, есть конфликт с Python2) для установки зависимостей:
```
pip install -r requirements.txt
```
3. Рекомендуется использовать [virtualenv/venv](https://docs.python.org/3/library/venv.html) для изоляции проекта.

4. Создать поисковой зопрос на Avito и положить ссылку на него в файл `.env` под именем `SEARCH_URL`

4. Для работы с Telegram потребуется:
    * Получить `bot token` и положить его в `.env` под именем `TG_BOT_TOKEN`, об этом [здесь](https://smmplanner.com/blog/otlozhennyj-posting-v-telegram/);
    * Получить `bot token` для бота-логера, требуемого для отслеживания ошибок в работе парсера и ботов. Полученный token в `.env` под именем `TG_LOG_BOT_TOKEN`;
    * Получить свой `id` у `@userinfobot` и положить в `.env` под именем `TG_CHAT_ID`.

5. Завести бесплатную базу данных на [redislabs.com](https://redislabs.com/), получить адрес, порт и пароль от базы и положить их в `.env` под именами `DB_HOST`, `DB_PORT` и `DB_PASSWORD` соответственно.

6. Запустить файл `tg_bot.py`.
