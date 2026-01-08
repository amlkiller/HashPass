// worker.js - 挖矿 Worker
// 注意：这个 Worker 使用 type="module" 来支持 ESM
import { argon2id } from "https://esm.sh/hash-wasm@4.12.0";

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

async function startMining({ seed, visitorId, traceData, difficulty, memoryCost, timeCost, parallelism }) {
  let nonce = 0;
  const saltString = seed + visitorId + traceData;
  const salt = new TextEncoder().encode(saltString);

  const startTime = Date.now();
  let lastUpdateTime = Date.now();

  self.postMessage({
    type: "LOG",
    message: `开始计算 Argon2id (内存=${memoryCost/1024}MB, 时间=${timeCost}, 并行=${parallelism})...`,
  });

  while (mining) {
    nonce++;

    try {
      const hash = await argon2id({
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

      // 每2秒更新一次速率和进度
      if (timeSinceLastUpdate >= 2.0 || nonce % 10 === 0) {
        const elapsed = (currentTime - startTime) / 1000;
        const hashRate = elapsed > 0 ? (nonce / elapsed).toFixed(2) : "0.00";

        // 发送进度日志（每10次）
        if (nonce % 10 === 0) {
          self.postMessage({
            type: "PROGRESS",
            nonce: nonce,
            hash: hash.substring(0, 16),
            elapsed: elapsed.toFixed(1),
          });
        }

        // 发送哈希速率更新（每2秒）
        if (timeSinceLastUpdate >= 2.0) {
          self.postMessage({
            type: "HASH_RATE",
            hashRate: hashRate,
          });
          lastUpdateTime = currentTime;
        }
      }

      // 检查是否找到解
      if (hash.startsWith("0".repeat(difficulty))) {
        const elapsed = ((Date.now() - startTime) / 1000).toFixed(2);
        self.postMessage({
          type: "SOLUTION_FOUND",
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
        message: error.message,
      });
      mining = false;
      return;
    }
  }
}
