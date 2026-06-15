"""命令行接口"""
import typer
from rich.console import Console
from rich.table import Table

from quant.convert import (convert_stock_quote, convert_margin_trade, convert_adjust, convert_margin_trade_daily,
                           convert_ta, convert_boll, convert_fund_shares, convert_fund_quote, convert_fund_adjust,
                           convert_fund_flow, convert_index_quote, convert_index_ta, convert_index_boll,
                           convert_fwd_return, convert_historical_stats, convert_filter_volume_spike,
                           convert_filter_ma_converge,
                           convert_fund_hs300_correlation)
from quant.pipeline import build_stages, run_pipeline

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
def filter_volume_spike(
    input_dir: str,
    min_market_cap: float,
    lookback_days: int = 5,
    min_ratio: float = 2.0,
    ma_period: int = 10,
    min_date: str = None,
    min_zt_days: int = 0,
    input_dir_adj: str = None,
    output_csv: str = None,
) -> None:
    """筛选放量股票：市值达标 + 成交额放量 + 涨停天数"""
    console.print(f"[cyan]筛选放量股票...[/cyan]")
    results = convert_filter_volume_spike(input_dir=input_dir, min_market_cap=min_market_cap,
                                          lookback_days=lookback_days, min_ratio=min_ratio,
                                          ma_period=ma_period, min_date=min_date, min_zt_days=min_zt_days,
                                          input_dir_adj=input_dir_adj)

    if not results:
        console.print("[yellow]没有找到符合条件的股票[/yellow]")
        return

    # 显示表格
    table = Table(title=f"放量股票筛选结果 (共 {len(results)} 只)")
    table.add_column("代码", style="cyan")
    table.add_column("市值", style="yellow")
    table.add_column("最新日期", style="blue")
    table.add_column("放量日期", style="red")
    table.add_column("放量倍数", style="bright_red")
    table.add_column("涨停天数", style="green")

    for r in results[:100]:
        table.add_row(
            r["code"],
            f"{r['market_cap']/1e8:.0f}亿",
            r["latest_date"],
            r["spike_date"],
            f"{r['spike_ratio']:.2f}x",
            f"{r['zt_days']}天",
        )

    console.print(table)

    if len(results) > 100:
        console.print(f"[dim]... 还有 {len(results) - 100} 只股票未显示[/dim]")

    # 导出 CSV
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
    results = convert_filter_ma_converge(
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


if __name__ == "__main__":
    cli(prog_name="quant")