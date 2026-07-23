"""
测试 Pipeline[T]：Stage 注册、执行、短路。
"""

from __future__ import annotations

from src.runtime._pipeline import Pipeline, Stage, StopPipelineError


class UpperStage(Stage[str]):
    """将输入转为大写的 Stage。"""

    async def process(self, input: str, ctx) -> str:
        return input.upper()


class ExclaimStage(Stage[str]):
    """在输入后加感叹号的 Stage。"""

    async def process(self, input: str, ctx) -> str:
        return input + "!"


class ConditionalStage(Stage[str]):
    """条件执行的 Stage。"""

    def __init__(self, should: bool = True) -> None:
        self._should = should

    async def should_run(self, ctx) -> bool:
        return self._should

    async def process(self, input: str, ctx) -> str:
        return input + "[conditional]"


class StopStage(Stage[str]):
    """中途停止的 Stage。"""

    async def process(self, input: str, ctx) -> str:
        raise StopPipelineError()


class TestPipeline:
    """测试 Pipeline 核心功能。"""

    async def test_empty_pipeline(self) -> None:
        pipeline = Pipeline[str]()
        result = await pipeline.execute("hello", None)
        assert result.output == "hello"
        assert result.executed_stages == []
        assert result.stopped_early is False

    async def test_single_stage(self) -> None:
        pipeline = Pipeline[str]()
        pipeline.add(UpperStage())
        result = await pipeline.execute("hello", None)
        assert result.output == "HELLO"
        assert result.executed_stages == ["stage_0_UpperStage"]

    async def test_multiple_stages_order(self) -> None:
        pipeline = Pipeline[str]()
        pipeline.add(ExclaimStage(), order=2)
        pipeline.add(UpperStage(), order=1)
        result = await pipeline.execute("hello", None)
        # upper 先执行 → "HELLO"，然后 exclaim → "HELLO!"
        assert result.output == "HELLO!"

    async def test_multiple_stages_insertion_order(self) -> None:
        pipeline = Pipeline[str]()
        pipeline.add(UpperStage())
        pipeline.add(ExclaimStage())
        result = await pipeline.execute("hello", None)
        assert result.output == "HELLO!"

    async def test_stage_id_custom(self) -> None:
        pipeline = Pipeline[str]()
        stage_id = pipeline.add(UpperStage(), id="upper", order=1)
        assert stage_id == "upper"

        result = await pipeline.execute("hello", None)
        assert result.executed_stages == ["upper"]

    async def test_remove_stage(self) -> None:
        pipeline = Pipeline[str]()
        pipeline.add(UpperStage(), id="upper")
        pipeline.add(ExclaimStage(), id="exclaim")

        pipeline.remove("upper")
        result = await pipeline.execute("hello", None)
        assert result.executed_stages == ["exclaim"]

    async def test_remove_nonexistent(self) -> None:
        pipeline = Pipeline[str]()
        try:
            pipeline.remove("nonexistent")
            assert False, "应该抛出 ValueError"
        except ValueError:
            pass

    async def test_replace_stage(self) -> None:
        pipeline = Pipeline[str]()
        pipeline.add(UpperStage(), id="stage1")
        pipeline.replace("stage1", ExclaimStage())

        result = await pipeline.execute("hello", None)
        # ExclaimStage: "hello" + "!" = "hello!"
        assert result.output == "hello!"

    async def test_replace_nonexistent(self) -> None:
        pipeline = Pipeline[str]()
        try:
            pipeline.replace("nonexistent", UpperStage())
            assert False, "应该抛出 ValueError"
        except ValueError:
            pass

    async def test_enable_disable(self) -> None:
        pipeline = Pipeline[str]()
        pipeline.add(UpperStage(), id="upper")
        pipeline.add(ExclaimStage(), id="exclaim")

        pipeline.enable("upper", enabled=False)
        result = await pipeline.execute("hello", None)
        assert result.executed_stages == ["exclaim"]
        assert result.output == "hello!"

    async def test_conditional_stage_skipped(self) -> None:
        pipeline = Pipeline[str]()
        pipeline.add(UpperStage(), id="upper")
        pipeline.add(ConditionalStage(should=False), id="cond")
        pipeline.add(ExclaimStage(), id="exclaim")

        result = await pipeline.execute("hello", None)
        assert "cond" not in result.executed_stages
        assert result.output == "HELLO!"

    async def test_conditional_stage_executed(self) -> None:
        pipeline = Pipeline[str]()
        pipeline.add(UpperStage(), id="upper")
        pipeline.add(ConditionalStage(should=True), id="cond")
        pipeline.add(ExclaimStage(), id="exclaim")

        result = await pipeline.execute("hello", None)
        assert "cond" in result.executed_stages
        assert result.output == "HELLO[conditional]!"

    async def test_stop_pipeline_early(self) -> None:
        pipeline = Pipeline[str]()
        pipeline.add(UpperStage(), id="upper")
        pipeline.add(StopStage(), id="stop")
        pipeline.add(ExclaimStage(), id="exclaim")

        result = await pipeline.execute("hello", None)
        assert result.stopped_early is True
        assert result.executed_stages == ["upper", "stop"]
        # stop stage 抛出异常，此阶段 output 是上一阶段的输出
        assert result.output == "HELLO"

    async def test_snapshots(self) -> None:
        pipeline = Pipeline[str](record_snapshots=True)
        pipeline.add(UpperStage(), id="upper")
        pipeline.add(ExclaimStage(), id="exclaim")

        result = await pipeline.execute("hello", None)
        assert len(result.snapshots) == 2
        assert result.snapshots[0][0] == "upper"
        assert result.snapshots[0][1] == "hello"  # input
        assert result.snapshots[0][2] == "HELLO"  # output

    async def test_generic_type_with_int(self) -> None:
        """测试泛型类型为 int 的场景。"""

        class DoubleStage(Stage[int]):
            async def process(self, input: int, ctx) -> int:
                return input * 2

        pipeline = Pipeline[int]()
        pipeline.add(DoubleStage())
        result = await pipeline.execute(5, None)
        assert result.output == 10
