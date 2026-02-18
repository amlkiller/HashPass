import ipaddress
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class PuzzleRequest(BaseModel):
    visitorId: str = Field(max_length=128)


class PuzzleResponse(BaseModel):
    seed: str
    difficulty: int
    memory_cost: int
    time_cost: int
    parallelism: int
    worker_count: int
    puzzle_start_time: float
    last_solve_time: Optional[float] = None
    average_solve_time: Optional[float] = None

class Submission(BaseModel):
    visitorId: str = Field(max_length=128)       # ThumbmarkJS 指纹
    nonce: int = Field(ge=0, le=2**53)           # 挖矿 nonce
    submittedSeed: str = Field(max_length=128)   # 提交时的 seed
    traceData: str = Field(max_length=2048)      # Cloudflare trace 数据
    hash: str = Field(max_length=256)            # 计算出的哈希值

class VerifyResponse(BaseModel):
    invite_code: str


# ===== Admin 请求模型 =====

class AdminDifficultyUpdate(BaseModel):
    difficulty: Optional[int] = None
    min_difficulty: Optional[int] = None
    max_difficulty: Optional[int] = None

class AdminTargetTimeUpdate(BaseModel):
    target_time_min: Optional[int] = None
    target_time_max: Optional[int] = None

class AdminArgon2Update(BaseModel):
    time_cost: Optional[int] = None
    memory_cost: Optional[int] = None
    parallelism: Optional[int] = None

class AdminWorkerCountUpdate(BaseModel):
    worker_count: int

class AdminMaxNonceSpeedUpdate(BaseModel):
    max_nonce_speed: float  # nonce/s，0 表示禁用

class AdminHmacUpdate(BaseModel):
    hmac_secret: str  # hex 编码的 HMAC 密钥

class AdminKickRequest(BaseModel):
    ip: str

    @field_validator("ip")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f"Invalid IP address: {v!r}")
        return v

class AdminUnbanRequest(BaseModel):
    ip: str

    @field_validator("ip")
    @classmethod
    def validate_ip(cls, v: str) -> str:
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError(f"Invalid IP address: {v!r}")
        return v
