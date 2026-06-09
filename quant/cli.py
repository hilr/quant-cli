"""命令行接口"""
import typer
from rich.console import Console

from quant.convert import convert_stock_quote, convert_margin_trade, convert_adjust, convert_margin_trade_daily, convert_ma, convert_boll, convert_fund_shares, convert_fund_quote, convert_fund_adjust, convert_fund_flow, convert_index_quote, convert_index_ma, convert_index_boll, convert_fwd_return, convert_historical_stats

console = Console()
cli = typer.Typer(name="quant", help="命令行量化工具")


@cli.command()
def stock_quote(
    data_path: str,
    source: str,
    output_dir: str,
) -> None:
    """将每日股票行情数据转换为每个股票的历史数据"""
    console.print(f"[cyan]读取 {source} 股票行情数据...[/cyan]")
    count = convert_stock_quote(data_path=data_path, source=source, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只股票[/green]")


@cli.command()
def index_quote(
    data_path: str,
    source: str,
    output_dir: str,
) -> None:
    """将每日指数行情数据转换为每个指数的历史数据"""
    console.print(f"[cyan]读取 {source} 指数行情数据...[/cyan]")
    count = convert_index_quote(data_path=data_path, source=source, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 个指数[/green]")


@cli.command()
def index_ma(
    input_dir: str,
    output_dir: str,
) -> None:
    """基于指数行情计算 close 和 turnover 的滚动均线"""
    console.print(f"[cyan]计算指数均线...[/cyan]")
    count = convert_index_ma(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 个指数[/green]")


@cli.command()
def index_boll(
    input_dir: str,
    output_dir: str,
) -> None:
    """基于指数行情计算布林带"""
    console.print(f"[cyan]计算指数布林带...[/cyan]")
    count = convert_index_boll(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 个指数[/green]")


@cli.command()
def margin_trade(
    data_path: str,
    source: str,
    output_dir: str,
) -> None:
    """将每日融资融券数据转换为每个标的的历史数据"""
    console.print(f"[cyan]读取 {source} 融资融券数据...[/cyan]")
    count = convert_margin_trade(data_path=data_path, source=source, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只标的[/green]")


@cli.command()
def adjust(
    input_dir: str,
    output_dir: str,
) -> None:
    """前复权：将股票历史价格按最新价格向前调整"""
    console.print(f"[cyan]前复权计算...[/cyan]")
    count = convert_adjust(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只股票[/green]")


@cli.command()
def margin_trade_daily(
    input_dir: str,
    output_dir: str,
) -> None:
    """从个股文件生成每日融资融券净变化汇总（最新日期往前，存在则跳过）"""
    console.print(f"[cyan]生成每日净变化文件...[/cyan]")
    count = convert_margin_trade_daily(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 个日期文件[/green]")


@cli.command()
def ma(
    input_dir: str,
    output_dir: str,
) -> None:
    """基于前复权数据计算 close 的滚动均线（ma5/10/20/60/120/250）"""
    console.print(f"[cyan]计算均线...[/cyan]")
    count = convert_ma(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只股票[/green]")


@cli.command()
def boll(
    input_dir: str,
    output_dir: str,
) -> None:
    """基于前复权数据计算布林带（period=20/60, k=2）"""
    console.print(f"[cyan]计算布林带...[/cyan]")
    count = convert_boll(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只股票[/green]")


@cli.command()
def fund_shares(
    data_path: str,
    output_dir: str,
) -> None:
    """将 SSE + SZSE 基金份额数据转换为每基金历史数据"""
    console.print(f"[cyan]处理基金份额...[/cyan]")
    count = convert_fund_shares(data_path=data_path, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只基金[/green]")


@cli.command()
def fund_quote(
    data_path: str,
    source: str,
    output_dir: str,
) -> None:
    """将基金行情数据转换为每基金历史数据"""
    console.print(f"[cyan]读取 {source} 基金行情数据...[/cyan]")
    count = convert_fund_quote(data_path=data_path, source=source, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只基金[/green]")


@cli.command()
def fund_adjust(
    input_dir: str,
    output_dir: str,
) -> None:
    """前复权：将基金历史价格按最新价格向前调整"""
    console.print(f"[cyan]基金前复权计算...[/cyan]")
    count = convert_fund_adjust(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只基金[/green]")


@cli.command()
def fund_flow(
    shares_dir: str,
    quote_dir: str,
    output_dir: str,
) -> None:
    """结合份额变动和收盘价，估算每日加减仓金额"""
    console.print(f"[cyan]计算基金资金流...[/cyan]")
    count = convert_fund_flow(shares_dir=shares_dir, quote_dir=quote_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只基金[/green]")


@cli.command()
def fwd_return(
    input_dir: str,
    output_dir: str,
) -> None:
    """基于复权后数据计算每日的未来5/10日收益率特征"""
    console.print(f"[cyan]计算前向收益...[/cyan]")
    count = convert_fwd_return(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只股票[/green]")


@cli.command()
def historical_stats(
    input_dir: str,
    output_dir: str,
) -> None:
    """计算股票过去250/120/60/20天的最高价、最低价、收益率、当前收盘价"""
    console.print(f"[cyan]计算历史统计数据...[/cyan]")
    count = convert_historical_stats(input_dir=input_dir, output_dir=output_dir)
    console.print(f"[green]完成! 共 {count} 只股票[/green]")


if __name__ == "__main__":
    cli(prog_name="quant")