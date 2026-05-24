from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


class PostgresSettings(BaseSettings):
    dbname: str = Field(..., alias="POSTGRES_DB")
    user: str = Field(..., alias="POSTGRES_USER")
    password: str = Field(..., alias="POSTGRES_PASSWORD")
    host: str = Field(..., alias="SQL_HOST")
    port: int = Field(..., alias="DB_PORT")
    options: str = Field(..., alias="SQL_OPTIONS")

    model_config = SettingsConfigDict(env_file=None)


class ElasticsearchSettings(BaseSettings):
    host: str = Field(..., alias="ELASTICSEARCH_HOST")
    port: int = Field(..., alias="ELASTICSEARCH_PORT")

    model_config = SettingsConfigDict(env_file=None)


class ETLSettings(BaseSettings):
    batch_size: int = Field(..., alias="ETL_BATCH_SIZE")
    cron_schedule: str = Field(..., alias="ETL_CRON_SCHEDULE")
    state_file_path: str = "state.json"

    model_config = SettingsConfigDict(env_file=None)


class Config(BaseSettings):
    postgres: PostgresSettings = PostgresSettings()
    elasticsearch: ElasticsearchSettings = ElasticsearchSettings()
    etl: ETLSettings = ETLSettings()

    model_config = SettingsConfigDict(env_file=None)


config = Config()
