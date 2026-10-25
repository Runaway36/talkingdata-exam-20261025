# Qwen v3 第三轮请求诊断重放

日期：2026-10-25（北京时间）。本目录仅为一次单请求诊断，不是新的正式评测 episode，不修改或替换原始失败结果。

## 原始失败与诊断丢失

原始运行：`../../qwen25-15b-run01/seed17-attempt01/`。

原始 `result.json` 为 `execution_error`、`reward: null`；已完成两轮响应，第三轮请求已保存，但没有成功响应。

`local_qwen_driver.py` 的 `_error` 将未列入特殊映射且不属于 `ValueError` 的异常统一转为 `Local model operation failed; see diagnostic type on stderr`。请求异常处理随后将同一个精简结果写入 stderr，没有写 traceback 或原始错误消息。因此旧结果仅保留 `RuntimeError` 类型，无法据此识别具体 Torch/CUDA 错误。

本次代码修改只增加标准库 `traceback`，在模型加载异常及请求异常处向 stderr 写完整 traceback 并 flush；stdout 仍保持单行 JSON 错误协议。模型加载、精度、采样和任务业务逻辑未变。

## 本次重放输入与边界

- 输入：原始 `turn-03-request.json`，原字节另存为本目录 `request.json`。
- 原请求 SHA256：`33638cae2b3cc75b41ed795efaaa5c3689647b7d9c7180b0c0ef41e5533775c7`。
- 6 条 messages，`max_tokens=1024`，`temperature=0.7`，`sampling_seed=20262728`。
- 显式 `--device cuda`；实际 `cuda:0`、`torch.bfloat16`，未改 CPU、精度或预算，未下载模型。
- 只重放该请求一次，不重跑前两轮，不重启正式批次。

## 实际结果

- 子进程退出码 0，没有超时，总墙钟时间 19.43667789999745 秒。
- 加载 6.210184700001264 秒；请求生成 3.2459885999996914 秒。
- 输入 2778 tokens，输出 51 tokens，`finish_reason=stop`。
- 输出为调用 `get_incident_services` 的 JSON，参数包含 `INC-AUTH`、`INC-BASE`；完整输出见 `stdout.jsonl`。
- 本次没有产生异常 traceback；加载诊断见 `stderr.txt`。
- 子进程已结束，模型进程与其 GPU 分配已释放。

## 能证明与不能证明的结论

已确认错误日志处理存在信息丢失，并已修复保存 traceback 的路径。单独重放这一请求本次可以执行。

原始模型执行错误的具体根因仍查不到。本次成功不证明原错误已经解决，也不能证明它是网络、显存、数值精度或模型能力问题。独立重放重新创建了进程、模型和 CUDA 上下文，没有保留原始前两轮之后的运行状态。

原始正式 episode 继续保留 `execution_error`、`reward: null`。本目录不是完整作答，不能将重放成功当作原始 episode 通过或用于填补正式模型得分。

建议如需继续正式批次，由主调度明确创建新的尝试目录，保留旧失败；再次出现错误时读取已补全的 traceback 后再决定针对性修复。不要据本次单次成功自动切换设备、精度或采样参数。
