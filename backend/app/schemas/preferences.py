from pydantic import BaseModel


class PreferenceItem(BaseModel):
    category: str
    weight: float


class PreferencesUpdate(BaseModel):
    items: list[PreferenceItem]


class PreferencesResponse(BaseModel):
    items: list[PreferenceItem]
