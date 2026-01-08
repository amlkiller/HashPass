"""测试进程池执行器"""
import asyncio
from src.core.executor import init_process_pool, get_process_pool, shutdown_process_pool
from src.core.crypto import verify_argon2_solution


async def test_process_pool():
    """测试进程池并行化验证"""
    print("[Test] Initializing process pool...")
    init_process_pool()

    print("[Test] Getting process pool...")
    executor = get_process_pool()
    print(f"[Test] Executor: {executor}")

    # 测试验证函数
    print("\n[Test] Testing Argon2 verification in process pool...")

    loop = asyncio.get_running_loop()

    # 模拟参数（这个测试不会通过验证，只是测试调用）
    test_params = {
        "nonce": 12345,
        "seed": "test_seed_123",
        "visitor_id": "test_visitor",
        "trace_data": "ip=127.0.0.1",
        "submitted_hash": "0" * 64,
        "difficulty": 1,
        "time_cost": 3,
        "memory_cost": 65536,
        "parallelism": 1
    }

    print(f"[Test] Running verification with params: {test_params}")

    # 在进程池中运行验证
    is_valid, error_message = await loop.run_in_executor(
        executor,
        verify_argon2_solution,
        test_params["nonce"],
        test_params["seed"],
        test_params["visitor_id"],
        test_params["trace_data"],
        test_params["submitted_hash"],
        test_params["difficulty"],
        test_params["time_cost"],
        test_params["memory_cost"],
        test_params["parallelism"]
    )

    print(f"[Test] Result: is_valid={is_valid}, error={error_message}")

    print("\n[Test] Shutting down process pool...")
    shutdown_process_pool(wait=True)

    print("[Test] All tests completed successfully!")


if __name__ == "__main__":
    asyncio.run(test_process_pool())
