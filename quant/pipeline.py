"""数据集流水线：按依赖拓扑排序执行，同层并行"""
from dataclasses import dataclass, field
from concurrent.futures import ProcessPoolExecutor, as_completed

from .convert import (
    convert_stock_quote, convert_index_quote,
    convert_margin_trade, convert_margin_trade_daily,
    convert_adjust, convert_fund_adjust,
    convert_ta, convert_index_ta,
    convert_fund_shares, convert_fund_quote, convert_fund_flow,
    convert_fund_hs300_correlation,
    convert_etf_universe,
    convert_pbc_money_supply, convert_pbc_social_financing_flow,
    convert_pbc_social_financing_stock, convert_pbc_credit_funds,
    convert_pbc_central_bank_balance_sheet,
    convert_gov_stat_trade, convert_gov_stat_retail_sales,
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
            Step("pbc_social_financing_flow", convert_pbc_social_financing_flow, dict(data_path=data_path, output_dir=output_dir)),
            Step("pbc_social_financing_stock", convert_pbc_social_financing_stock, dict(data_path=data_path, output_dir=output_dir)),
            Step("pbc_credit_funds", convert_pbc_credit_funds, dict(data_path=data_path, output_dir=output_dir)),
            Step("pbc_central_bank_balance_sheet", convert_pbc_central_bank_balance_sheet, dict(data_path=data_path, output_dir=output_dir)),
            Step("gov_stat_trade", convert_gov_stat_trade, dict(data_path=data_path, output_dir=output_dir)),
            Step("gov_stat_retail_sales", convert_gov_stat_retail_sales, dict(data_path=data_path, output_dir=output_dir)),
        ],
        # Stage 2: 前复权 + 货币供应量（依赖 Stage 1 的 pbc_credit_funds）
        [
            Step("stock_quote_adjusted", convert_adjust, dict(input_dir=f"{output_dir}/stock_quote_history", output_dir=f"{output_dir}/stock_quote_adjusted")),
            Step("fund_quote_adjusted", convert_fund_adjust, dict(input_dir=f"{output_dir}/fund_quote_history", output_dir=f"{output_dir}/fund_quote_adjusted")),
            Step("pbc_money_supply", convert_pbc_money_supply,
                 dict(data_path=data_path, output_dir=output_dir, credit_funds_csv=f"{output_dir}/pbc/credit_funds.csv")),
        ],
        # Stage 3: 衍生指标
        [
            Step("stock_quote_ta", convert_ta, dict(input_dir=f"{output_dir}/stock_quote_adjusted", output_dir=f"{output_dir}/stock_quote_ta")),
            Step("index_quote_ta", convert_index_ta, dict(input_dir=f"{output_dir}/index_quote_history", output_dir=f"{output_dir}/index_quote_ta")),
        ],
        # Stage 4: 聚合数据
        [
            Step("margin_trade_daily", convert_margin_trade_daily, dict(input_dir=f"{output_dir}/margin_trade_history", output_dir=f"{output_dir}/margin_trade_daily")),
            Step("fund_flow", convert_fund_flow, dict(shares_dir=f"{output_dir}/fund_shares_history", quote_dir=f"{output_dir}/fund_quote_adjusted", output_dir=f"{output_dir}/fund_flow")),
            Step("fund_hs300_correlation", convert_fund_hs300_correlation, dict(input_dir=f"{output_dir}/fund_quote_adjusted", output_dir=f"{output_dir}/fund_hs300_correlation")),
            Step("etf_universe", convert_etf_universe, dict(input_dir=f"{output_dir}/fund_quote_adjusted", output_dir=f"{output_dir}/etf_universe")),
        ],
    ]


def build_equity_stages(data_path: str, output_dir: str) -> list[list[Step]]:
    """股票链：stock_quote_history → stock_quote_adjusted → stock_quote_ta"""
    return [
        [Step("stock_quote_history", convert_stock_quote, dict(data_path=data_path, output_dir=output_dir))],
        [Step("stock_quote_adjusted", convert_adjust, dict(input_dir=f"{output_dir}/stock_quote_history", output_dir=f"{output_dir}/stock_quote_adjusted"))],
        [Step("stock_quote_ta", convert_ta, dict(input_dir=f"{output_dir}/stock_quote_adjusted", output_dir=f"{output_dir}/stock_quote_ta"))],
    ]


def build_index_stages(data_path: str, output_dir: str) -> list[list[Step]]:
    """指数链：index_quote_history → index_quote_ta"""
    return [
        [Step("index_quote_history", convert_index_quote, dict(data_path=data_path, output_dir=output_dir))],
        [Step("index_quote_ta", convert_index_ta, dict(input_dir=f"{output_dir}/index_quote_history", output_dir=f"{output_dir}/index_quote_ta"))],
    ]


def build_fund_stages(data_path: str, output_dir: str) -> list[list[Step]]:
    """基金链：fund_shares + fund_quote → fund_quote_adjusted → fund_flow + fund_hs300_correlation + etf_universe"""
    return [
        [
            Step("fund_shares_history", convert_fund_shares, dict(data_path=data_path, output_dir=output_dir)),
            Step("fund_quote_history", convert_fund_quote, dict(data_path=data_path, output_dir=output_dir)),
        ],
        [Step("fund_quote_adjusted", convert_fund_adjust, dict(input_dir=f"{output_dir}/fund_quote_history", output_dir=f"{output_dir}/fund_quote_adjusted"))],
        [
            Step("fund_flow", convert_fund_flow, dict(shares_dir=f"{output_dir}/fund_shares_history", quote_dir=f"{output_dir}/fund_quote_adjusted", output_dir=f"{output_dir}/fund_flow")),
            Step("fund_hs300_correlation", convert_fund_hs300_correlation, dict(input_dir=f"{output_dir}/fund_quote_adjusted", output_dir=f"{output_dir}/fund_hs300_correlation")),
            Step("etf_universe", convert_etf_universe, dict(input_dir=f"{output_dir}/fund_quote_adjusted", output_dir=f"{output_dir}/etf_universe")),
        ],
    ]


def build_margin_stages(data_path: str, output_dir: str) -> list[list[Step]]:
    """融资融券链：margin_trade_history → margin_trade_daily"""
    return [
        [Step("margin_trade_history", convert_margin_trade, dict(data_path=data_path, output_dir=output_dir))],
        [Step("margin_trade_daily", convert_margin_trade_daily, dict(input_dir=f"{output_dir}/margin_trade_history", output_dir=f"{output_dir}/margin_trade_daily"))],
    ]


def build_macro_stages(data_path: str, output_dir: str) -> list[list[Step]]:
    """宏观数据集：PBC + gov_stat。pbc_money_supply 依赖 pbc_credit_funds 的输出，故分两 stage"""
    credit_csv = f"{output_dir}/pbc/credit_funds.csv"
    return [
        [
            Step("pbc_credit_funds", convert_pbc_credit_funds, dict(data_path=data_path, output_dir=output_dir)),
            Step("pbc_social_financing_flow", convert_pbc_social_financing_flow, dict(data_path=data_path, output_dir=output_dir)),
            Step("pbc_social_financing_stock", convert_pbc_social_financing_stock, dict(data_path=data_path, output_dir=output_dir)),
            Step("pbc_central_bank_balance_sheet", convert_pbc_central_bank_balance_sheet, dict(data_path=data_path, output_dir=output_dir)),
            Step("gov_stat_trade", convert_gov_stat_trade, dict(data_path=data_path, output_dir=output_dir)),
            Step("gov_stat_retail_sales", convert_gov_stat_retail_sales, dict(data_path=data_path, output_dir=output_dir)),
        ],
        [Step("pbc_money_supply", convert_pbc_money_supply,
              dict(data_path=data_path, output_dir=output_dir, credit_funds_csv=credit_csv))],
    ]


def run_step(step: Step) -> int:
    """执行单个步骤（供进程池调用）"""
    return step.func(**step.kwargs)


def run_pipeline(stages: list[list[Step]], workers: int = 2,
                 console=None, stage_names: list[str] | None = None) -> None:
    """逐 stage 执行，每 stage 内并行"""
    default_names = [
        "原始数据 → 历史数据",
        "前复权",
        "衍生指标",
        "聚合数据",
    ]

    for stage_idx, stage in enumerate(stages):
        if stage_names and stage_idx < len(stage_names):
            name = stage_names[stage_idx]
        elif stage_idx < len(default_names):
            name = default_names[stage_idx]
        else:
            name = f"Stage {stage_idx + 1}"
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
