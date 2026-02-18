// worker.js - 挖矿 Worker
// 注意：这个 Worker 使用 type="module" 来支持 ESM
import { argon2d } from "https://esm.sh/hash-wasm@4.12.0";

function countLeadingZeroBits(hexHash) {
  let bits = 0;
  for (const c of hexHash) {
    const nibble = parseInt(c, 16);
    if (nibble === 0) {
      bits += 4;
    } else {
      if (nibble < 2) bits += 3;
      else if (nibble < 4) bits += 2;
      else if (nibble < 8) bits += 1;
      break;
    }
  }
  return bits;
}

let mining = false;

// 接收主线程消息
self.onmessage = async function (e) {
  const { type, data } = e.data;

  if (type === "START_MINING") {
    mining = true;
    await startMining(data);
  } else if (type === "STOP_MINING") {
    mining = false;
    self.postMessage({ type: "STOPPED" });
  }
};

async function startMining({
  seed,
  visitorId,
  ip,
  difficulty,
  memoryCost,
  timeCost,
  parallelism,
  workerId = 0,
  workerCount = 1,
}) {
  let nonce = workerId; // 起始 nonce = workerId
  const saltString = seed + "|" + visitorId + "|" + ip;
  const salt = new TextEncoder().encode(saltString);

  const WINDOW_SIZE = 10; // 滑动窗口大小（保留最近 N 次哈希的时间戳）
  const hashTimestamps = []; // 滑动窗口时间戳队列
  const startTime = Date.now(); // 用于计算总耗时
  let lastUpdateTime = Date.now();
  let hashCount = 0; // 实际哈希次数

  self.postMessage({
    type: "LOG",
    workerId,
    message: `[Worker ${workerId}] 开始计算 Argon2d (内存=${memoryCost / 1024}MB, 时间=${timeCost}, 并行=${parallelism})...`,
  });

  while (mining) {
    hashCount++;

    try {
      const hash = await argon2d({
        password: nonce.toString(),
        salt: salt,
        memorySize: memoryCost,
        iterations: timeCost,
        parallelism: parallelism,
        hashLength: 32,
        outputType: "hex",
      });

      const currentTime = Date.now();
      const timeSinceLastUpdate = (currentTime - lastUpdateTime) / 1000;

      // 记录到滑动窗口
      hashTimestamps.push(currentTime);
      if (hashTimestamps.length > WINDOW_SIZE) {
        hashTimestamps.shift();
      }

      // 每2秒更新一次速率和进度
      if (timeSinceLastUpdate >= 2.0 || hashCount % 10 === 0) {
        // 滑动窗口速率：窗口内哈希数 / 窗口时间跨度
        let hashRate = "0.00";
        if (hashTimestamps.length >= 2) {
          const windowSpan = (hashTimestamps[hashTimestamps.length - 1] - hashTimestamps[0]) / 1000;
          if (windowSpan > 0) {
            hashRate = ((hashTimestamps.length - 1) / windowSpan).toFixed(2);
          }
        }

        // 发送进度日志（每10次）
        if (hashCount % 10 === 0) {
          const elapsed = ((currentTime - startTime) / 1000).toFixed(1);
          self.postMessage({
            type: "PROGRESS",
            workerId,
            nonce: nonce,
            hash: hash.substring(0, 16),
            elapsed: elapsed,
          });
        }

        // 发送哈希速率更新（每2秒）
        if (timeSinceLastUpdate >= 2.0) {
          self.postMessage({
            type: "HASH_RATE",
            workerId,
            hashRate: hashRate,
          });
          lastUpdateTime = currentTime;
        }
      }

      // 检查是否找到解
      if (countLeadingZeroBits(hash) >= difficulty) {
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);
        self.postMessage({
          type: "SOLUTION_FOUND",
          workerId,
          nonce: nonce,
          hash: hash,
          elapsed: elapsed,
        });
        mining = false;
        return;
      }
    } catch (error) {
      self.postMessage({
        type: "ERROR",
        workerId,
        message: error.message,
      });
      mining = false;
      return;
    }

    // stride: 步长为 workerCount
    nonce += workerCount;
  }
}
