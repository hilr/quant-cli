"""数据集流水线：按依赖拓扑排序执行，同层并行"""
from dataclasses import dataclass, field
from concurrent.futures import ProcessPoolExecutor, as_completed

from .convert import (
    convert_stock_quote, convert_index_quote,
    convert_margin_trade, convert_margin_trade_daily,
    convert_adjust, convert_fund_adjust,
    convert_ma, convert_boll, convert_index_ma, convert_index_boll,
    convert_fwd_return, convert_historical_stats,
    convert_fund_shares, convert_fund_quote, convert_fund_flow,
)


@dataclass
class Step:
    name: str
    func: callable
    kwargs: dict = field(default_factory=dict)


def build_stages(data_path: str, output_dir: str) -> list[list[Step]]:
    """根据路径参数构建依赖阶段列表"""
    return [
        # Stage 1: 原始数据 → 历史数据
        [
            Step("stock_quote_history", convert_stock_quote, dict(data_path=data_path, output_dir=output_dir)),
            Step("margin_trade_history", convert_margin_trade, dict(data_path=data_path, output_dir=output_dir)),
            Step("fund_shares_history", convert_fund_shares, dict(data_path=data_path, output_dir=output_dir)),
            Step("fund_quote_history", convert_fund_quote, dict(data_path=data_path, output_dir=output_dir)),
            Step("index_quote_history", convert_index_quote, dict(data_path=data_path, output_dir=output_dir)),
        ],
        # Stage 2: 前复权
        [
            Step("stock_quote_adjusted", convert_adjust, dict(input_dir=f"{output_dir}/stock_quote_history", output_dir=f"{output_dir}/stock_quote_adjusted")),
            Step("fund_quote_adjusted", convert_fund_adjust, dict(input_dir=f"{output_dir}/fund_quote_history", output_dir=f"{output_dir}/fund_quote_adjusted")),
        ],
        # Stage 3: 衍生指标
        [
            Step("stock_quote_ma", convert_ma, dict(input_dir=f"{output_dir}/stock_quote_adjusted", output_dir=f"{output_dir}/stock_quote_ma")),
            Step("stock_quote_boll", convert_boll, dict(input_dir=f"{output_dir}/stock_quote_adjusted", output_dir=f"{output_dir}/stock_quote_boll")),
            Step("stock_historical_stats", convert_historical_stats, dict(input_dir=f"{output_dir}/stock_quote_adjusted", output_dir=f"{output_dir}/stock_historical_stats")),
            Step("stock_fwd_return", convert_fwd_return, dict(input_dir=f"{output_dir}/stock_quote_adjusted", output_dir=f"{output_dir}/stock_fwd_return")),
            Step("index_quote_ma", convert_index_ma, dict(input_dir=f"{output_dir}/index_quote_history", output_dir=f"{output_dir}/index_quote_ma")),
            Step("index_quote_boll", convert_index_boll, dict(input_dir=f"{output_dir}/index_quote_history", output_dir=f"{output_dir}/index_quote_boll")),
        ],
        # Stage 4: 聚合数据
        [
            Step("margin_trade_daily", convert_margin_trade_daily, dict(input_dir=f"{output_dir}/margin_trade_history", output_dir=f"{output_dir}/margin_trade_daily")),
            Step("fund_flow", convert_fund_flow, dict(shares_dir=f"{output_dir}/fund_shares_history", quote_dir=f"{output_dir}/fund_quote_adjusted", output_dir=f"{output_dir}/fund_flow")),
        ],
    ]


def run_step(step: Step) -> int:
    """执行单个步骤（供进程池调用）"""
    return step.func(**step.kwargs)


def run_pipeline(stages: list[list[Step]], workers: int = 2, console=None) -> None:
    """逐 stage 执行，每 stage 内并行"""
    stage_names = [
        "原始数据 → 历史数据",
        "前复权",
        "衍生指标",
        "聚合数据",
    ]

    for stage_idx, stage in enumerate(stages):
        name = stage_names[stage_idx] if stage_idx < len(stage_names) else f"Stage {stage_idx + 1}"
        if console:
            console.print(f"\n[bold cyan]Stage {stage_idx + 1}: {name}[/bold cyan]")

        max_workers = min(workers, len(stage))
        failed = []

        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(run_step, step): step for step in stage}
            for future in as_completed(futures):
                step = futures[future]
                try:
                    count = future.result()
                    if console:
                        console.print(f"  [green]✓ {step.name}: {count}[/green]")
                except Exception as e:
                    failed.append((step.name, e))
                    if console:
                        console.print(f"  [red]✗ {step.name}: {e}[/red]")

        if failed:
            if console:
                console.print(f"\n[red]Stage {stage_idx + 1} 失败: {len(failed)} 个步骤[/red]")
            raise RuntimeError(f"Stage {stage_idx + 1} failed: {[f[0] for f in failed]}")
