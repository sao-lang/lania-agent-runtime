"""
Pipeline 剩余分支覆盖。
"""

from __future__ import annotations

import pytest

from src.runtime._pipeline import Pipeline, Stage, StopPipelineError


class TestPipelineRemainingBranches:
    """Pipeline 剩余分支。"""

    async def test_stop_pipeline_with_snapshots(self) -> None:
        """StopPipelineError + record_snapshots=True。"""

        class StopStage(Stage[str]):
            async def process(self, input: str, ctx) -> str:
                raise StopPipelineError()

        pipeline = Pipeline[str](record_snapshots=True)
        pipeline.add(StopStage(), id="stop")
        result = await pipeline.execute("hello", None)
        assert result.stopped_early is True
        assert len(result.snapshots) == 1
        assert result.snapshots[0][0] == "stop"

    async def test_enable_nonexistent_id(self) -> None:
        """enable 不存在的 ID 抛出 ValueError。"""
        pipeline = Pipeline[str]()
        with pytest.raises(ValueError, match="不存在"):
            pipeline.enable("nonexistent")
