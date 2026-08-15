from pydantic import BaseModel


class PreferenceItem(BaseModel):
    category: str
    enabled: bool


class PreferencesUpdate(BaseModel):
    items: list[PreferenceItem]


class PreferencesResponse(BaseModel):
    items: list[PreferenceItem]
