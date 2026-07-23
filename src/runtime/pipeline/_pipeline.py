"""
通用管线框架——Pipeline[T]。

应用于：ContextManager 五阶段管线、StepRunner 单步管线、Memory 读写管线。
有序 Stage 依次执行，每阶段可替换。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


class Stage(ABC, Generic[T]):
    """
    管线中的一个阶段。

    所有具体 Stage 应继承此类并实现 process 方法。
    可通过覆写 should_run 实现条件执行。
    """

    @abstractmethod
    async def process(self, input: T, ctx: Any) -> T:
        """
        处理输入并返回输出。

        Args:
            input: 输入数据。
            ctx: RuntimeContext 实例。

        Returns:
            处理后的输出数据。
        """
        ...

    async def should_run(self, ctx: Any) -> bool:
        """
        判断当前阶段是否应执行。

        Args:
            ctx: RuntimeContext 实例。

        Returns:
            True 表示执行，False 表示跳过。
        """
        return True


@dataclass
class StageInfo(Generic[T]):
    """管线阶段元信息。"""

    id: str
    """阶段唯一标识。"""
    stage: Stage[T]
    """阶段实例。"""
    order: int = 0
    """执行顺序（值越小越先执行）。"""
    enabled: bool = True
    """是否启用。"""


@dataclass
class PipelineResult(Generic[T]):
    """管线执行结果。"""

    output: T
    """最终输出。"""
    executed_stages: list[str]
    """实际执行的阶段 ID 列表（按执行顺序）。"""
    stopped_early: bool = False
    """是否提前终止。"""
    snapshots: list[tuple[str, Any, Any]] = field(default_factory=list)
    """每阶段的 (stage_id, input, output) 快照（用于调试和可观测性）。"""


class StopPipelineError(Exception):
    """抛出此异常可提前终止管线执行。"""


class Pipeline(Generic[T]):
    """
    通用管线——按序执行一组 Stage。

    能力:
    - add / remove / replace / enable / disable 任意 Stage
    - 短路（任一 Stage 可抛出 StopPipeline 终止）
    - 快照（记录每 Stage 的输入输出，用于调试和可观测性）
    - 自动跳过 disabled 或 should_run 返回 False 的 Stage
    """

    def __init__(self, record_snapshots: bool = False) -> None:
        """
        初始化管线。

        Args:
            record_snapshots: 是否记录每阶段的输入输出快照（默认 False）。
        """
        self._stages: list[StageInfo[T]] = []
        self._record_snapshots = record_snapshots

    def add(
        self,
        stage: Stage[T],
        *,
        order: int = 0,
        id: str = "",
    ) -> str:
        """
        添加一个 Stage 到管线。

        Args:
            stage: Stage 实例。
            order: 执行顺序（值越小越先执行）。
            id: 阶段唯一标识。若不提供则自动生成。

        Returns:
            阶段 ID。
        """
        stage_id = id or f"stage_{len(self._stages)}_{stage.__class__.__name__}"
        info = StageInfo(id=stage_id, stage=stage, order=order)
        self._stages.append(info)
        self._stages.sort(key=lambda s: s.order)
        return stage_id

    def remove(self, id: str) -> None:
        """
        移除指定 ID 的 Stage。

        Args:
            id: 阶段 ID。

        Raises:
            ValueError: 如果 ID 不存在。
        """
        for i, info in enumerate(self._stages):
            if info.id == id:
                self._stages.pop(i)
                return
        raise ValueError(f"Stage '{id}' 不存在")

    def replace(self, id: str, stage: Stage[T]) -> None:
        """
        替换指定 ID 的 Stage。

        Args:
            id: 要替换的阶段 ID。
            stage: 新的 Stage 实例。

        Raises:
            ValueError: 如果 ID 不存在。
        """
        for info in self._stages:
            if info.id == id:
                info.stage = stage
                return
        raise ValueError(f"Stage '{id}' 不存在")

    def enable(self, id: str, enabled: bool = True) -> None:
        """
        启用或禁用指定 ID 的 Stage。

        Args:
            id: 阶段 ID。
            enabled: True 启用，False 禁用。

        Raises:
            ValueError: 如果 ID 不存在。
        """
        for info in self._stages:
            if info.id == id:
                info.enabled = enabled
                return
        raise ValueError(f"Stage '{id}' 不存在")

    async def execute(self, input: T, ctx: Any) -> PipelineResult[T]:
        """
        按 order 升序执行 Stage。

        Args:
            input: 输入数据。
            ctx: RuntimeContext 实例。

        Returns:
            PipelineResult 包含最终输出和执行记录。
        """
        data = input
        executed: list[str] = []
        snapshots: list[tuple[str, Any, Any]] = []
        stopped_early = False

        for info in self._stages:
            if not info.enabled:
                continue

            if not await info.stage.should_run(ctx):
                continue

            stage_input = data
            try:
                data = await info.stage.process(data, ctx)
                executed.append(info.id)
                if self._record_snapshots:
                    snapshots.append((info.id, stage_input, data))
            except StopPipelineError:
                executed.append(info.id)
                if self._record_snapshots:
                    snapshots.append((info.id, stage_input, data))
                stopped_early = True
                break

        return PipelineResult(
            output=data,
            executed_stages=executed,
            stopped_early=stopped_early,
            snapshots=snapshots,
        )
