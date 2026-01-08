from pydantic import BaseModel

class PuzzleResponse(BaseModel):
    seed: str
    difficulty: int
    memory_cost: int
    time_cost: int
    parallelism: int

class Submission(BaseModel):
    visitorId: str      # ThumbmarkJS 指纹
    nonce: int          # 挖矿 nonce
    submittedSeed: str  # 提交时的 seed
    traceData: str      # Cloudflare trace 数据
    hash: str           # 计算出的哈希值

class VerifyResponse(BaseModel):
    invite_code: str
