# Веб-версия (этап 3)

Здесь будет сайт на Next.js. Бэкенд для него уже готов: сайт — ещё один клиент к тому же ядру (`core`), что и бот.
Пользователь входит через Telegram и видит тот же баланс и ту же историю, что в боте.

## API ядра, которое использует сайт

| Метод | Путь | Назначение |
|---|---|---|
| POST | `/v1/auth/telegram` | Вход: передать данные из [виджета Telegram Login](https://core.telegram.org/widgets/login), получить `access_token` |
| GET | `/v1/me` | Профиль и баланс |
| GET | `/v1/models` | Список моделей |
| PUT | `/v1/me/model` | Выбрать модель `{"model": "..."}` |
| GET | `/v1/conversations` | Список диалогов |
| POST | `/v1/conversations` | Новый диалог |
| GET | `/v1/conversations/{id}/messages` | Сообщения диалога |
| POST | `/v1/chat` | Отправить сообщение `{"message", "model"?, "conversation_id"?}`, ответ — поток SSE |

Все методы, кроме `/v1/models` и `/v1/auth/telegram`, требуют заголовок `Authorization: Bearer <access_token>`.
Полная интерактивная документация: `http://<ядро>:8000/docs`.

## Что сделать при старте веба

1. `npx create-next-app@latest web` (из корня репозитория).
2. Подключить виджет Telegram Login (домен сайта нужно указать у @BotFather командой `/setdomain`).
3. Указать адрес сайта в `CORS_ORIGINS` в `.env`.
4. Добавить сервис `web` в `docker-compose.yml`.
5. Платежи на сайте: ЮKassa / CloudPayments. Их уведомления (webhook) зачислять через тот же `billing.topup` в ядре — для этого понадобится добавить в ядро обработчик webhook-а нужной платёжки.
