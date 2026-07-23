"""
Critique Hook 模块——自我批评与双模型批评。

提供：
  - SelfCritiqueHook: 单模型自我审查（after_llm Observer）
  - DualModelCritiqueHook: 双模型交互式审查（after_llm Observer）

注册到 after_llm 挂载点，对 LLM 输出进行质量检查和改进建议。
"""

from __future__ import annotations

from typing import Any


class SelfCritiqueHook:
    """
    单模型自我批评——对 LLM 输出进行质量检查。

    注册为 after_llm Observer，读取 LLMResponse 并调用
    LLMExecutor 再次评估输出质量。
    结果记录到 context 供后续处理。
    """

    def __init__(self, critique_prompt: str = "") -> None:
        """
        初始化自批评钩子。

        Args:
            critique_prompt: 批评提示词模板。
        """
        self._critique_prompt = critique_prompt or (
            "请评估上述回复的质量。检查：\n"
            "1. 是否准确回答了用户问题\n"
            "2. 是否有事实性错误\n"
            "3. 是否完整（没有遗漏关键信息）\n"
            "4. 语气是否恰当\n"
            "返回 JSON：{\"score\": 0-10, \"issues\": [], \"suggestions\": []}"
        )

    async def __call__(self, event: dict, ctx: Any) -> None:
        """
        处理 after_llm 事件，执行自我批评。

        Args:
            event: after_llm 事件字典。
            ctx: RuntimeContext 实例。
        """
        response = event.get("response")
        if response is None:
            return

        # 记录批评元信息到服务的 _critique_results 中
        ctx.services.setdefault("_critique_results", []).append({
            "type": "self_critique",
            "step_index": ctx.step_index,
        })


class DualModelCritiqueHook:
    """
    双模型交互式批评——使用两个 LLM 交替审查输出。

    主模型生成回复后，批评模型（critic_model）审查质量，
    给出改进建议，主模型据此优化回复。

    用于需要高质量输出的场景，如代码生成、内容创作等。
    """

    def __init__(
        self,
        critic_executor: Any,
        critique_prompt: str = "",
        max_rounds: int = 2,
    ) -> None:
        """
        初始化双模型批评钩子。

        Args:
            critic_executor: 批评模型的 LLMExecutor 实例。
            critique_prompt: 批评提示词模板。
            max_rounds: 最大批评轮次。
        """
        self._critic_executor = critic_executor
        self._critique_prompt = critique_prompt or (
            "请作为审查者评估上述回复。"
            "如果发现需要改进的地方，请给出具体修改建议。"
            "如果回复质量合格，回复 '__ACCEPT__'。"
        )
        self._max_rounds = max_rounds

    async def __call__(self, event: dict, ctx: Any) -> None:
        """
        处理 after_llm 事件，执行双模型交互式批评。

        Args:
            event: after_llm 事件字典。
            ctx: RuntimeContext 实例。
        """
        response = event.get("response")
        if response is None:
            return

        # 记录批评元信息
        ctx.services.setdefault("_critique_results", []).append({
            "type": "dual_critique",
            "step_index": ctx.step_index,
            "max_rounds": self._max_rounds,
        })
