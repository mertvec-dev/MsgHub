from pydantic import BaseModel, Field

class E2EKeyRequest(BaseModel):
    """Схема для запроса публичного ключа E2E"""
    algorithm: str = Field(default="x25519")
    public_key: str = Field(min_length=32, max_length=4096)

class PublicKeyResponse(BaseModel):
    """Схема для ответа с публичным ключом E2E"""
    user_id: int
    algorithm: str
    public_key: str


class DevicePublicKeyRequest(BaseModel):
    device_id: str = Field(min_length=8, max_length=255)
    public_key: str = Field(min_length=32, max_length=4096)
    algorithm: str = Field(default="p256-ecdh-v1", max_length=64)
    device_name: str | None = Field(default=None, max_length=255)
    device_type: str | None = Field(default=None, max_length=64)


class DevicePublicKeyResponse(BaseModel):
    user_id: int
    device_id: str
    algorithm: str
    public_key: str


class PeerDeviceKeyItem(BaseModel):
    user_id: int
    device_id: str
    algorithm: str
    public_key: str


class PeerDeviceKeysResponse(BaseModel):
    user_id: int
    devices: list[PeerDeviceKeyItem]

class RoomKeyEnvelopeItem(BaseModel):
    """Схема для конверта с публичным ключом E2E для шифрования сообщений в комнате"""
    user_id: int
    encrypted_key: str = Field(min_length=32, max_length=4096)
    algorithm: str = Field(default="x25519")

class RoomKeyEnvelopeUpsertRequest(BaseModel):
    """Схема для запроса на обновление конверта с публичным ключом E2E для шифрования сообщений в комнате"""
    key_version: int = Field(..., ge=1) # версия ключа для шифрования ge = больше или равно 1
    envelopes: list[RoomKeyEnvelopeItem] = Field(..., min_length=1) # список конвертов с публичными ключами E2E для шифрования сообщений в комнате

class RoomKeyEnvelopeResponse(BaseModel):
    """Схема для ответа с конвертом с публичным ключом E2E для шифрования сообщений в комнате"""
    room_id: int
    user_id: int
    key_version: int
    encrypted_key: str
    algorithm: str

class RoomKeyRotateResponse(BaseModel):
    """Схема для ответа с информацией о вращении ключа"""
    room_id: int
    current_key_version: int