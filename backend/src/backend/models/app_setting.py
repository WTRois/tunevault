from sqlmodel import Field, SQLModel


class AppSetting(SQLModel, table=True):
    """Runtime key-value app settings (blueprint §10 release preferences).

    Simple durable overrides the user can change at runtime without a
    redeploy; every absent key falls back to config defaults.
    """

    __tablename__ = "app_settings"

    key: str = Field(primary_key=True)
    value: str = Field(default="")