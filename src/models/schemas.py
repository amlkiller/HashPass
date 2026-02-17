from typing import Optional

from pydantic import BaseModel


class PuzzleResponse(BaseModel):
    seed: str
    difficulty: int
    memory_cost: int
    time_cost: int
    parallelism: int
    worker_count: int

class Submission(BaseModel):
    visitorId: str      # ThumbmarkJS 指纹
    nonce: int          # 挖矿 nonce
    submittedSeed: str  # 提交时的 seed
    traceData: str      # Cloudflare trace 数据
    hash: str           # 计算出的哈希值

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

class AdminKickRequest(BaseModel):
    ip: str

class AdminUnbanRequest(BaseModel):
    ip: str
