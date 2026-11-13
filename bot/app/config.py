from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str
    core_url: str = "http://core:8000"
    service_token: str

    # Пополнение через Telegram Stars
    stars_packs: str = "50,100,250,500"  # варианты пополнения в звёздах
    kopecks_per_star: int = 100  # сколько копеек баланса даёт 1 звезда — настройте под свою экономику

    support_contact: str = "@your_support"  # для /paysupport (обязателен для ботов, принимающих Stars)

    @property
    def stars_pack_list(self) -> list[int]:
        return [int(x) for x in self.stars_packs.split(",") if x.strip()]


settings = Settings()
