"""命令行接口"""
import typer
from rich.console import Console
from rich.table import Table

from quant.convert import (convert_stock_quote, convert_margin_trade, convert_adjust, convert_margin_trade_daily,
                           convert_ta, convert_boll, convert_fund_shares, convert_fund_quote, convert_fund_adjust,
                           convert_fund_flow, convert_index_quote, convert_index_ta, convert_index_boll,
                           convert_fwd_return, convert_historical_stats,
                           convert_fund_hs300_correlation, convert_industry_profit,
                           convert_pbc_money_supply, convert_pbc_social_financing_flow,
                           convert_pbc_social_financing_stock, convert_pbc_credit_funds,
                           convert_pbc_central_bank_balance_sheet)
from quant.filter import (filter_volume_spike as run_filter_volume_spike,
                          filter_ma_converge as run_filter_ma_converge,
                          filter_by_tags as run_filter_by_tags,
                          filter_limit_up_pullback as run_filter_limit_up_pullback)
from quant.tags import TAG_FUNCS
from quant.pipeline import build_stages, run_pipeline
from quant.strategy import run_momentum_strategy, run_ma_crossover_strategy

console = Console()
cli = typer.Typer(name="quant", help="命令行量化工具")


@cli.command()
def refresh(
    data_path: str = "/mnt/readonly_dataset",
    output_dir: str = "/mnt/dataset",
    workers: int = 2,
) -> None:
    """按依赖拓扑排序并行刷新全部数据集"""
    console.print(f"[cyan]开始刷新数据集（workers={workers}）...[/cyan]")
    stages = build_stages(data_path=data_path, output_dir=output_dir)
    run_pipeline(stages, workers=workers, console=console)
    console.print(f"\n[green]全部数据集刷新完成[/green]")


@cli.command()
def stock_quote(
    data_path: str = "/mnt/readonly_dataset",
    source: str = "finance_sina",
    output_dir: str = "/mnt/dataset",
) -> None:
    """将每日股票行情数据转换为每个股票的历史数据"""
    console.print(f"[cyan]读取 {source} 股票行情数据...[/cyan]")
    count = convert_stock_quote(data_path=data_path, source=source, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只股票[/green]")


@cli.command()
def index_quote(
    data_path: str = "/mnt/readonly_dataset",
    source: str = "finance_sina",
    output_dir: str = "/mnt/dataset",
) -> None:
    """将每日指数行情数据转换为每个指数的历史数据"""
    console.print(f"[cyan]读取 {source} 指数行情数据...[/cyan]")
    count = convert_index_quote(data_path=data_path, source=source, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 个指数[/green]")


@cli.command()
def index_ta(
    input_dir: str = "/mnt/dataset/index_quote_history",
    output_dir: str = "/mnt/dataset/index_quote_ta",
) -> None:
    """基于指数行情计算 close 和 turnover 的滚动均线"""
    console.print(f"[cyan]计算指数均线...[/cyan]")
    count = convert_index_ta(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 个指数[/green]")


@cli.command()
def index_boll(
    input_dir: str = "/mnt/dataset/index_quote_history",
    output_dir: str = "/mnt/dataset/index_quote_boll",
) -> None:
    """基于指数行情计算布林带"""
    console.print(f"[cyan]计算指数布林带...[/cyan]")
    count = convert_index_boll(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 个指数[/green]")


@cli.command()
def margin_trade(
    data_path: str = "/mnt/readonly_dataset",
    source: str = "eastmoney",
    output_dir: str = "/mnt/dataset",
) -> None:
    """将每日融资融券数据转换为每个标的的历史数据"""
    console.print(f"[cyan]读取 {source} 融资融券数据...[/cyan]")
    count = convert_margin_trade(data_path=data_path, source=source, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只标的[/green]")


@cli.command()
def adjust(
    input_dir: str = "/mnt/dataset/stock_quote_history",
    output_dir: str = "/mnt/dataset/stock_quote_adjusted",
) -> None:
    """前复权：将股票历史价格按最新价格向前调整"""
    console.print(f"[cyan]前复权计算...[/cyan]")
    count = convert_adjust(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只股票[/green]")


@cli.command()
def margin_trade_daily(
    input_dir: str = "/mnt/dataset/margin_trade_history",
    output_dir: str = "/mnt/dataset/margin_trade_daily",
) -> None:
    """从个股文件生成每日融资融券净变化汇总（最新日期往前，存在则跳过）"""
    console.print(f"[cyan]生成每日净变化文件...[/cyan]")
    count = convert_margin_trade_daily(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 个日期文件[/green]")


@cli.command()
def ta(
    input_dir: str = "/mnt/dataset/stock_quote_adjusted",
    output_dir: str = "/mnt/dataset/stock_quote_ta",
) -> None:
    """基于前复权数据计算均线、布林带、历史统计、前向收益等指标"""
    console.print(f"[cyan]计算均线...[/cyan]")
    count = convert_ta(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只股票[/green]")


@cli.command()
def boll(
    input_dir: str = "/mnt/dataset/stock_quote_adjusted",
    output_dir: str = "/mnt/dataset/stock_quote_boll",
) -> None:
    """基于前复权数据计算布林带（period=20/60, k=2）"""
    console.print(f"[cyan]计算布林带...[/cyan]")
    count = convert_boll(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只股票[/green]")


@cli.command()
def fund_shares(
    data_path: str = "/mnt/readonly_dataset",
    output_dir: str = "/mnt/dataset",
) -> None:
    """将 SSE + SZSE 基金份额数据转换为每基金历史数据"""
    console.print(f"[cyan]处理基金份额...[/cyan]")
    count = convert_fund_shares(data_path=data_path, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只基金[/green]")


@cli.command()
def fund_quote(
    data_path: str = "/mnt/readonly_dataset",
    source: str = "cninfo",
    output_dir: str = "/mnt/dataset",
) -> None:
    """将基金行情数据转换为每基金历史数据"""
    console.print(f"[cyan]读取 {source} 基金行情数据...[/cyan]")
    count = convert_fund_quote(data_path=data_path, source=source, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只基金[/green]")


@cli.command()
def fund_adjust(
    input_dir: str = "/mnt/dataset/fund_quote_history",
    output_dir: str = "/mnt/dataset/fund_quote_adjusted",
) -> None:
    """前复权：将基金历史价格按最新价格向前调整"""
    console.print(f"[cyan]基金前复权计算...[/cyan]")
    count = convert_fund_adjust(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只基金[/green]")


@cli.command()
def fund_flow(
    shares_dir: str = "/mnt/dataset/fund_shares_history",
    quote_dir: str = "/mnt/dataset/fund_quote_adjusted",
    output_dir: str = "/mnt/dataset/fund_flow",
) -> None:
    """结合份额变动和收盘价，估算每日加减仓金额"""
    console.print(f"[cyan]计算基金资金流...[/cyan]")
    count = convert_fund_flow(shares_dir=shares_dir, quote_dir=quote_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只基金[/green]")


@cli.command()
def fund_hs300_corr(
    input_dir: str = "/mnt/dataset/fund_quote_adjusted",
    output_dir: str = "/mnt/dataset/fund_hs300_correlation",
) -> None:
    """计算沪深300关联基金与510300的滚动相关性（5/10/20日窗口）"""
    console.print("[cyan]计算沪深300关联基金滚动相关性...[/cyan]")
    count = convert_fund_hs300_correlation(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只基金[/green]")


@cli.command()
def fwd_return(
    input_dir: str = "/mnt/dataset/stock_quote_adjusted",
    output_dir: str = "/mnt/dataset/stock_fwd_return",
) -> None:
    """基于复权后数据计算每日的未来5/10日收益率特征"""
    console.print(f"[cyan]计算前向收益...[/cyan]")
    count = convert_fwd_return(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只股票[/green]")


@cli.command()
def historical_stats(
    input_dir: str = "/mnt/dataset/stock_quote_adjusted",
    output_dir: str = "/mnt/dataset/stock_historical_stats",
) -> None:
    """计算股票过去250/120/60/20天的最高价、最低价、收益率、当前收盘价"""
    console.print(f"[cyan]计算历史统计数据...[/cyan]")
    count = convert_historical_stats(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只股票[/green]")


@cli.command()
def industry_profit(
    data_path: str = "/mnt/readonly_dataset",
    output_dir: str = "/mnt/dataset",
) -> None:
    """将工业企业利润累计值转换为每月当月利润总额，每年一个 CSV"""
    console.print(f"[cyan]生成工业企业月度利润数据...[/cyan]")
    count = convert_industry_profit(data_path=data_path, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 个年度文件[/green]")


@cli.command()
def pbc_money_supply(
    data_path: str = "/mnt/readonly_dataset",
    output_dir: str = "/mnt/dataset",
) -> None:
    """央行货币供应量 M0/M1/M2 月度数据（亿元），宽表 date/m0/m1/m2，2004 起"""
    console.print(f"[cyan]生成央行货币供应量数据...[/cyan]")
    count = convert_pbc_money_supply(data_path=data_path, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 条月度记录[/green]")


@cli.command()
def pbc_social_financing_flow(
    data_path: str = "/mnt/readonly_dataset",
    output_dir: str = "/mnt/dataset",
) -> None:
    """社会融资规模增量（流量），长表 date/item/value（亿元），2012 起"""
    console.print(f"[cyan]生成社融增量数据...[/cyan]")
    count = convert_pbc_social_financing_flow(data_path=data_path, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 条记录[/green]")


@cli.command()
def pbc_social_financing_stock(
    data_path: str = "/mnt/readonly_dataset",
    output_dir: str = "/mnt/dataset",
) -> None:
    """社会融资规模存量，长表 date/item/stock/growth_rate（万亿元 / %），2015 起"""
    console.print(f"[cyan]生成社融存量数据...[/cyan]")
    count = convert_pbc_social_financing_stock(data_path=data_path, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 条记录[/green]")


@cli.command()
def pbc_credit_funds(
    data_path: str = "/mnt/readonly_dataset",
    output_dir: str = "/mnt/dataset",
) -> None:
    """金融机构信贷收支表（存贷款全明细），长表 date/currency/item/value（亿元），1999 起"""
    console.print(f"[cyan]生成信贷收支数据...[/cyan]")
    count = convert_pbc_credit_funds(data_path=data_path, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 条记录[/green]")


@cli.command()
def pbc_central_bank_balance_sheet(
    data_path: str = "/mnt/readonly_dataset",
    output_dir: str = "/mnt/dataset",
) -> None:
    """货币当局资产负债表（全明细），长表 date/item/value（亿元），1999 起"""
    console.print(f"[cyan]生成央行资产负债表数据...[/cyan]")
    count = convert_pbc_central_bank_balance_sheet(data_path=data_path, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 条记录[/green]")


@cli.command()
def filter_volume_spike(
    input_dir: str,
    output_csv: str,
    min_market_cap: float,
    min_ratio: float = 2.0,
    ma_period: int = 20,
    min_date: str = None,
) -> None:
    """扫描所有历史日期，批量筛每日触发放量的股票，输出单个 CSV"""
    console.print(f"[cyan]批量筛选历史放量股票...[/cyan]")
    count = run_filter_volume_spike(
        input_dir=input_dir, output_csv=output_csv,
        min_market_cap=min_market_cap, min_ratio=min_ratio,
        ma_period=ma_period, min_date=min_date,
    )
    console.print(f"[green]完成! 共 {count} 条放量记录 → {output_csv}[/green]")


@cli.command()
def filter_by_tags(
    date: str = typer.Argument(..., help="指定日期 (YYYY-MM-DD)"),
    tags: list[str] = typer.Argument(..., help=f"Tag 名（AND 组合，可多个）。可选: {list(TAG_FUNCS.keys())}"),
    input_dir: str = "/mnt/dataset/stock_quote_ta",
    min_market_cap: float = 0,
    exclude_st: bool = True,
    output_csv: str = None,
) -> None:
    """筛选指定日期同时命中所有 tags 的股票（AND 组合）"""
    console.print(f"[cyan]筛选 tag 组合 ({date}, tags={tags})...[/cyan]")
    try:
        results = run_filter_by_tags(
            input_dir=input_dir, date=date, tags=tags,
            min_market_cap=min_market_cap, exclude_st=exclude_st,
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if not results:
        console.print("[yellow]没有找到符合条件的股票[/yellow]")
        return

    table = Table(title=f"Tag 命中股票 (共 {len(results)} 只, tags={'+'.join(tags)})")
    table.add_column("代码", style="cyan")
    table.add_column("收盘价", style="white")
    table.add_column("市值", style="yellow")

    for r in results[:100]:
        table.add_row(
            r["code"],
            f"{r['close']:.2f}",
            f"{r['market_cap']/1e8:.0f}亿",
        )

    console.print(table)

    if len(results) > 100:
        console.print(f"[dim]... 还有 {len(results) - 100} 只股票未显示[/dim]")

    if output_csv:
        import csv
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        console.print(f"[green]结果已导出: {output_csv}[/green]")


@cli.command()
def filter_limit_up_pullback(
    date: str,
    input_dir: str = "/mnt/dataset/stock_quote_ta",
    min_market_cap: float = 100e8,
    lookback_days: int = 10,
    max_calendar_span: int = 14,
    pullback_tolerance: float = 0.01,
    output_csv: str = None,
) -> None:
    """复合 filter：近期 tag_limit_up + 回踩到涨停前价位"""
    console.print(f"[cyan]筛选涨停回踩股票 ({date})...[/cyan]")
    results = run_filter_limit_up_pullback(
        input_dir=input_dir, date=date,
        min_market_cap=min_market_cap, lookback_days=lookback_days,
        max_calendar_span=max_calendar_span, pullback_tolerance=pullback_tolerance,
    )

    if not results:
        console.print("[yellow]没有找到符合条件的股票[/yellow]")
        return

    table = Table(title=f"涨停回踩股票 (共 {len(results)} 只)")
    table.add_column("代码", style="cyan")
    table.add_column("收盘价", style="white")
    table.add_column("市值", style="yellow")
    table.add_column("涨停日", style="magenta")
    table.add_column("涨停前收", style="green")
    table.add_column("回踩幅度", style="bright_red")

    for r in results[:100]:
        table.add_row(
            r["code"],
            f"{r['close']:.2f}",
            f"{r['market_cap']/1e8:.0f}亿",
            r["zt_date"],
            f"{r['zt_prev_close']:.2f}",
            f"{r['pullback_pct']:.2%}",
        )

    console.print(table)

    if len(results) > 100:
        console.print(f"[dim]... 还有 {len(results) - 100} 只股票未显示[/dim]")

    if output_csv:
        import csv
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        console.print(f"[green]结果已导出: {output_csv}[/green]")


@cli.command()
def filter_ma_converge(
    date: str,
    input_dir: str = "/mnt/dataset/stock_quote_ta",
    min_market_cap: float = 200e8,
    min_turnover: float = 10e8,
    max_ma_spread: float = 0.1,
    output_csv: str = None,
) -> None:
    """筛选均线收敛股票：市值达标 + 非ST + 成交额达标 + 均线收敛"""
    console.print(f"[cyan]筛选均线收敛股票 ({date})...[/cyan]")
    results = run_filter_ma_converge(
        ma_dir=input_dir, date=date,
        min_market_cap=min_market_cap, min_turnover=min_turnover,
        max_ma_spread=max_ma_spread,
    )

    if not results:
        console.print("[yellow]没有找到符合条件的股票[/yellow]")
        return

    table = Table(title=f"均线收敛股票 (共 {len(results)} 只)")
    table.add_column("代码", style="cyan")
    table.add_column("收盘价", style="white")
    table.add_column("市值", style="yellow")
    table.add_column("成交额", style="blue")
    table.add_column("MA max", style="green")
    table.add_column("MA min", style="green")
    table.add_column("MA spread", style="bright_red")

    for r in results[:100]:
        table.add_row(
            r["code"],
            f"{r['close']:.2f}",
            f"{r['market_cap']/1e8:.0f}亿",
            f"{r['turnover']/1e8:.1f}亿",
            f"{r['ma_max']:.2f}",
            f"{r['ma_min']:.2f}",
            f"{r['ma_spread']:.2%}",
        )

    console.print(table)

    if len(results) > 100:
        console.print(f"[dim]... 还有 {len(results) - 100} 只股票未显示[/dim]")

    if output_csv:
        import csv
        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        console.print(f"[green]结果已导出: {output_csv}[/green]")


@cli.command()
def momentum_strategy(
    input_dir: str = "/mnt/dataset/index_quote_history",
    output_csv: str = None,
    output_png: str = None,
    cash_when_all_negative: bool = False,
) -> None:
    """月度动量轮动策略：CSI300/CSI500/创业板50 每月末选当月最强者持有"""
    if output_csv is None:
        console.print("[red]必须提供 --output-csv[/red]")
        raise typer.Exit(1)
    console.print(f"[cyan]运行月度动量轮动策略...[/cyan]")
    stats = run_momentum_strategy(
        input_dir=input_dir, output_csv=output_csv, output_png=output_png,
        cash_when_all_negative=cash_when_all_negative,
    )

    table = Table(title="策略统计")
    table.add_column("指标", style="cyan")
    table.add_column("值", style="yellow")
    for k, v in stats.items():
        if isinstance(v, float):
            if k in ("total_return", "cagr", "annual_vol", "max_drawdown", "time_in_market"):
                table.add_row(k, f"{v:.2%}")
            elif k == "sharpe":
                table.add_row(k, f"{v:.2f}")
            else:
                table.add_row(k, f"{v:.4f}")
        else:
            table.add_row(k, str(v))
    console.print(table)
    console.print(f"[green]明细: {output_csv}[/green]")
    if output_png:
        console.print(f"[green]NAV 曲线: {output_png}[/green]")


@cli.command()
def ma_crossover_strategy(
    input_dir: str = "/mnt/dataset/index_quote_history",
    index_code: str = "000300",
    fast_window: int = 5,
    slow_window: int = 60,
    output_csv: str = None,
    output_png: str = None,
) -> None:
    """双均线突破策略：快线上穿慢线买入，跌破卖出"""
    if output_csv is None:
        console.print("[red]必须提供 --output-csv[/red]")
        raise typer.Exit(1)
    console.print(f"[cyan]运行双均线突破策略 ({index_code}, {fast_window}/{slow_window})...[/cyan]")
    stats = run_ma_crossover_strategy(
        input_dir=input_dir, output_csv=output_csv, output_png=output_png,
        index_code=index_code, fast_window=fast_window, slow_window=slow_window,
    )

    table = Table(title="策略统计")
    table.add_column("指标", style="cyan")
    table.add_column("值", style="yellow")
    for k, v in stats.items():
        if isinstance(v, float):
            if k in ("total_return", "cagr", "annual_vol", "max_drawdown", "time_in_market"):
                table.add_row(k, f"{v:.2%}")
            elif k == "sharpe":
                table.add_row(k, f"{v:.2f}")
            else:
                table.add_row(k, f"{v:.4f}")
        else:
            table.add_row(k, str(v))
    console.print(table)
    console.print(f"[green]明细: {output_csv}[/green]")
    if output_png:
        console.print(f"[green]NAV 曲线: {output_png}[/green]")


if __name__ == "__main__":
    cli(prog_name="quant")