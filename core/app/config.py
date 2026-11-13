from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AI Aggregator"

    # Инфраструктура
    database_url: str = "postgresql+asyncpg://aggregator:aggregator@postgres:5432/aggregator"
    redis_url: str = ""  # пусто -> лимиты в памяти процесса (только для разработки)

    # Провайдер моделей. Пустой ключ -> тестовый режим (ответы-заглушки, без затрат)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    public_url: str = ""  # адрес сайта, передаётся в OpenRouter для статистики

    # Безопасность
    service_token: str  # общий секрет ядра и бота
    jwt_secret: str  # подпись токенов веб-сессий
    jwt_ttl_hours: int = 24 * 30
    bot_token: str = ""  # нужен ядру для проверки входа через Telegram Login на сайте
    cors_origins: str = ""  # через запятую, напр. https://example.com

    # Деньги. Баланс хранится в копейках.
    usd_rub_rate: float = 100.0  # курс для пересчёта цен провайдера
    markup: float = 2.0  # наценка: итоговая цена = цена провайдера * markup
    welcome_bonus_kopecks: int = 1000  # стартовый бонус новому пользователю (10 ₽)
    min_balance_kopecks: int = 1  # ниже этого запросы не принимаются

    # Ограничения
    rate_limit_per_minute: int = 20
    history_messages: int = 20  # сколько прошлых сообщений отправлять модели как контекст
    max_message_chars: int = 16000
    default_model: str = "openai/gpt-4o-mini"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
