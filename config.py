from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # 自动从同目录 .env 读取，名字对应上即可
    deepseek_api_key: str
    app_api_key: str = "dev-secret-key"   # 调用方要带的钥匙

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()