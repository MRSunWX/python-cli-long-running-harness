#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自主编程助手 Agent 命令行入口 (main.py)
=====================================

本文件是项目的命令行接口（CLI），提供以下命令：
- init: 初始化新项目
- run: 运行 Agent 执行编码任务
- status: 查看项目状态和进度
- chat: 与 Agent 进行交互式对话

使用方式:
    python main.py init <project_dir> --spec "创建一个 Flask 应用"
    python main.py run <project_dir>
    python main.py status <project_dir>
    python main.py chat <project_dir>

依赖:
    click: 命令行参数解析
    rich: 终端美化输出
"""

import os
import sys
import click
from datetime import datetime
from typing import Optional

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入项目模块
from config import Config, set_project_dir
from agent import CodingAgent
from agent.progress import ProgressManager
from agent.event_logger import setup_event_logger, emit_event

# 尝试导入 rich 进行美化输出
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.markdown import Markdown
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# 创建控制台实例（如果 rich 可用）
if RICH_AVAILABLE:
    console = Console()


# ============================================
# 命令行主组和选项
# ============================================

@click.group()
@click.option('--model', default=None, help='模型名称（默认从配置读取）')
@click.option('--url', default=None, help='OpenAI 兼容 API 地址')
@click.option('--verbose', '-v', is_flag=True, help='显示详细输出')
@click.option(
    '--verbose-events/--quiet-events',
    default=Config.VERBOSE_EVENTS_DEFAULT,
    help='是否输出详细事件日志（默认开启）'
)
@click.pass_context
def cli(ctx, model, url, verbose, verbose_events):
    """
    自主编程助手 Agent

    一个基于大语言模型的自主编程 Agent，
    能够自主完成软件开发任务。

    \b
    示例:
      # 初始化新项目
      python main.py init ./my_project --spec "创建一个 Flask Web 应用"

      # 运行 Agent
      python main.py run ./my_project

      # 查看状态
      python main.py status ./my_project
    """
    # 将选项保存到上下文中，供子命令使用
    ctx.ensure_object(dict)
    ctx.obj['model'] = model or Config.MODEL_NAME
    ctx.obj['url'] = url or Config.OPENAI_BASE_URL
    ctx.obj['verbose'] = verbose
    ctx.obj['verbose_events'] = verbose_events


def _build_session_id(command_name: str) -> str:
    """
    生成命令级会话 ID

    参数:
        command_name: 命令名称（如 init/run）

    返回:
        str: 格式化的会话 ID
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{command_name}-{timestamp}"


def _start_command_event_log(command_name: str, project_dir: str, verbose_events: bool) -> None:
    """
    初始化命令事件日志并发送会话开始事件

    参数:
        command_name: 命令名称
        project_dir: 项目目录
        verbose_events: 是否输出详细事件日志
    """
    setup_event_logger(
        project_dir=project_dir,
        verbose_events=verbose_events,
        persist_file=True,
        phase=command_name,
        session_id=_build_session_id(command_name)
    )
    emit_event(
        event_type="session_start",
        component="cli",
        name=command_name,
        payload={"message": f"开始执行命令: {command_name}", "project_dir": project_dir},
        ok=True,
        phase=command_name
    )


def _end_command_event_log(command_name: str, success: bool, summary: str) -> None:
    """
    发送命令会话结束事件

    参数:
        command_name: 命令名称
        success: 命令是否成功
        summary: 结果摘要
    """
    emit_event(
        event_type="session_end",
        component="cli",
        name=command_name,
        payload={"message": summary, "summary": summary},
        ok=success,
        phase=command_name
    )


# ============================================
# init 命令 - 初始化项目
# ============================================

@cli.command()
@click.argument('project_dir', type=click.Path())
@click.option('--spec', '-s', required=True, help='项目需求描述')
@click.option('--name', '-n', default=None, help='项目名称（默认从目录名推断）')
@click.option('--template', '-t', default=None, help='项目模板（可选）')
@click.option(
    '--init-mode',
    type=click.Choice(['scaffold-only', 'open']),
    default='scaffold-only',
    show_default=True,
    help='初始化模式：scaffold-only 仅创建脚手架，open 允许初始化阶段继续实现'
)
@click.pass_context
def init(ctx, project_dir, spec, name, template, init_mode):
    """
    初始化新项目

    PROJECT_DIR: 项目目录路径

    \b
    示例:
      python main.py init ./my_app --spec "创建一个待办事项应用"
      python main.py init ./web_api --spec "创建 REST API" --name "MyAPI"
      python main.py init ./my_app --spec "创建一个待办事项应用" --init-mode open
    """
    model = ctx.obj['model']
    url = ctx.obj['url']
    verbose = ctx.obj['verbose']
    verbose_events = ctx.obj['verbose_events']

    _start_command_event_log("init", project_dir, verbose_events)

    # 打印标题
    if RICH_AVAILABLE:
        console.print(Panel.fit(
            "[bold blue]自主编程助手 Agent[/bold blue]\n"
            "[dim]自主编程助手 - 初始化模式[/dim]",
            border_style="blue"
        ))
    else:
        print("\n" + "="*50)
        print("自主编程助手 Agent - 初始化模式")
        print("="*50 + "\n")

    # 显示配置信息
    if verbose:
        if RICH_AVAILABLE:
            console.print(f"[dim]模型: {model}[/dim]")
            console.print(f"[dim]API: {url}[/dim]")
            console.print(f"[dim]目录: {project_dir}[/dim]")
        else:
            print(f"模型: {model}")
            print(f"API: {url}")
            print(f"目录: {project_dir}")

    # 创建 Agent 实例
    try:
        agent = CodingAgent(
            project_dir=project_dir,
            model_name=model,
            base_url=url
        )
    except Exception as e:
        if RICH_AVAILABLE:
            console.print(f"[red]错误: 创建 Agent 失败 - {str(e)}[/red]")
        else:
            print(f"错误: 创建 Agent 失败 - {str(e)}")
        sys.exit(1)

    # 推断项目名称
    if name is None:
        name = os.path.basename(os.path.abspath(project_dir))

    # 如果有模板，添加到需求中
    if template:
        spec = f"{spec}\n\n使用模板: {template}"

    # 执行初始化
    if RICH_AVAILABLE:
        console.print(f"\n[cyan]正在初始化项目...[/cyan]")
        console.print(f"[dim]需求: {spec[:100]}...[/dim]\n")
        console.print(f"[dim]初始化模式: {init_mode}[/dim]\n")
    else:
        print(f"\n正在初始化项目...")
        print(f"需求: {spec[:100]}...\n")
        print(f"初始化模式: {init_mode}\n")

    success = agent.initialize(
        requirements=spec,
        project_name=name,
        init_mode=init_mode,
    )

    if success:
        if RICH_AVAILABLE:
            console.print("\n[green]✓ 项目初始化完成！[/green]")
            console.print(f"\n[dim]下一步: python main.py run {project_dir}[/dim]")
        else:
            print("\n✓ 项目初始化完成！")
            print(f"\n下一步: python main.py run {project_dir}")
        _end_command_event_log("init", True, "项目初始化完成")
    else:
        if RICH_AVAILABLE:
            console.print("\n[red]✗ 项目初始化失败[/red]")
        else:
            print("\n✗ 项目初始化失败")
        _end_command_event_log("init", False, "项目初始化失败")
        sys.exit(1)


# ============================================
# run 命令 - 运行 Agent
# ============================================

@cli.command()
@click.argument('project_dir', type=click.Path(exists=True))
@click.option('--iterations', '-i', default=None, type=int, help='最大迭代次数')
@click.option('--continuous', '-c', is_flag=True, help='连续运行直到完成')
@click.option('--task', '-t', default=None, help='指定要执行的任务（功能 ID）')
@click.pass_context
def run(ctx, project_dir, iterations, continuous, task):
    """
    运行 Agent 执行编码任务

    PROJECT_DIR: 项目目录路径

    \b
    示例:
      python main.py run ./my_app
      python main.py run ./my_app --continuous
      python main.py run ./my_app --task feat-001
    """
    model = ctx.obj['model']
    url = ctx.obj['url']
    verbose = ctx.obj['verbose']
    verbose_events = ctx.obj['verbose_events']

    _start_command_event_log("run", project_dir, verbose_events)

    # 打印标题
    if RICH_AVAILABLE:
        console.print(Panel.fit(
            "[bold green]自主编程助手 Agent[/bold green]\n"
            "[dim]自主编程助手 - 运行模式[/dim]",
            border_style="green"
        ))
    else:
        print("\n" + "="*50)
        print("自主编程助手 Agent - 运行模式")
        print("="*50 + "\n")

    # 创建 Agent 实例
    try:
        agent = CodingAgent(
            project_dir=project_dir,
            model_name=model,
            base_url=url
        )
    except Exception as e:
        if RICH_AVAILABLE:
            console.print(f"[red]错误: 创建 Agent 失败 - {str(e)}[/red]")
        else:
            print(f"错误: 创建 Agent 失败 - {str(e)}")
        sys.exit(1)

    # 如果指定了特定任务
    if task:
        # 重置任务状态为待开始
        agent.reset_feature(task)
        if RICH_AVAILABLE:
            console.print(f"[cyan]执行指定任务: {task}[/cyan]\n")
        else:
            print(f"执行指定任务: {task}\n")

    # 运行模式选择
    if continuous:
        if RICH_AVAILABLE:
            console.print("[cyan]连续运行模式[/cyan]\n")
        else:
            print("连续运行模式\n")
        result = agent.run_continuous(
            max_total_iterations=iterations or 100
        )

        # 显示结果
        if RICH_AVAILABLE:
            console.print(f"\n[green]完成的功能: {len(result['completed_features'])}[/green]")
            console.print(f"[red]失败的功能: {len(result['failed_features'])}[/red]")
            if result.get('fatal_errors'):
                console.print(f"[red]关键错误: {result['fatal_errors'][0]}[/red]")
            _end_command_event_log("run", True, "连续运行结束")
        else:
            print(f"\n完成的功能: {len(result['completed_features'])}")
            print(f"失败的功能: {len(result['failed_features'])}")
            if result.get('fatal_errors'):
                print(f"关键错误: {result['fatal_errors'][0]}")
            _end_command_event_log("run", True, "连续运行结束")
    else:
        # 单次运行
        result = agent.run(max_iterations=iterations)

        if result.get('success'):
            if RICH_AVAILABLE:
                console.print(f"\n[green]✓ 任务完成[/green]")
                if result.get('feature_id'):
                    console.print(f"[dim]功能: {result['feature_id']}[/dim]")
            else:
                print(f"\n✓ 任务完成")
                if result.get('feature_id'):
                    print(f"功能: {result['feature_id']}")
            _end_command_event_log("run", True, "单次运行成功")
        else:
            if RICH_AVAILABLE:
                console.print(f"\n[red]✗ 任务失败: {result.get('error', '未知错误')}[/red]")
            else:
                print(f"\n✗ 任务失败: {result.get('error', '未知错误')}")
            _end_command_event_log("run", False, f"单次运行失败: {result.get('error', '未知错误')}")


# ============================================
# status 命令 - 查看状态
# ============================================

@cli.command('status')
@click.argument('project_dir', type=click.Path(exists=True))
@click.option('--json', 'output_json', is_flag=True, help='以 JSON 格式输出')
@click.pass_context
def status_cmd(ctx, project_dir, output_json):
    """
    查看项目状态和进度

    PROJECT_DIR: 项目目录路径

    \b
    示例:
      python main.py status ./my_app
      python main.py status ./my_app --json
    """
    # 创建进度管理器
    progress_manager = ProgressManager(project_dir)
    stats = progress_manager.get_progress_stats()
    feature_list = progress_manager.load_feature_list()

    if output_json:
        # JSON 格式输出
        import json
        output = {
            "project_dir": project_dir,
            "project_name": feature_list.project_name if feature_list else None,
            "stats": stats
        }
        print(json.dumps(output, indent=2, ensure_ascii=False))
        _end_command_event_log("status", True, "状态查询完成（JSON）")
        return

    # 美化输出
    if RICH_AVAILABLE:
        # 项目信息面板
        console.print(Panel.fit(
            f"[bold]项目状态[/bold]",
            border_style="blue"
        ))

        # 统计表格
        table = Table(title="进度统计")
        table.add_column("指标", style="cyan")
        table.add_column("值", style="green")

        table.add_row("项目名称", feature_list.project_name if feature_list else "未知")
        table.add_row("总功能数", str(stats['total']))
        table.add_row("已完成", str(stats['completed']))
        table.add_row("进行中", str(stats['in_progress']))
        table.add_row("待开始", str(stats['pending']))
        table.add_row("已阻塞", str(stats['blocked']))
        table.add_row("完成率", f"{stats['completion_rate']}%")

        console.print(table)

        # 功能列表
        if feature_list and feature_list.features:
            console.print("\n[bold]功能列表:[/bold]")

            feature_table = Table()
            feature_table.add_column("ID", style="dim")
            feature_table.add_column("名称")
            feature_table.add_column("状态")
            feature_table.add_column("优先级")

            status_colors = {
                "completed": "green",
                "in_progress": "yellow",
                "pending": "blue",
                "blocked": "red"
            }

            for feature in feature_list.features:
                status = feature.status
                color = status_colors.get(status, "white")
                feature_table.add_row(
                    feature.id,
                    feature.name,
                    f"[{color}]{status}[/{color}]",
                    feature.priority
                )

            console.print(feature_table)

    else:
        # 简单文本输出
        print("\n" + "="*50)
        print("项目状态")
        print("="*50)
        print(f"项目名称: {feature_list.project_name if feature_list else '未知'}")
        print(f"总功能数: {stats['total']}")
        print(f"已完成: {stats['completed']}")
        print(f"进行中: {stats['in_progress']}")
        print(f"待开始: {stats['pending']}")
        print(f"已阻塞: {stats['blocked']}")
        print(f"完成率: {stats['completion_rate']}%")

        if feature_list and feature_list.features:
            print("\n功能列表:")
            for feature in feature_list.features:
                print(f"  [{feature.id}] {feature.name} - {feature.status}")

    _end_command_event_log("status", True, "状态查询完成")


# ============================================
# chat 命令 - 交互式对话
# ============================================

@cli.command()
@click.argument('project_dir', type=click.Path(exists=True))
@click.pass_context
def chat(ctx, project_dir):
    """
    与 Agent 进行交互式对话

    PROJECT_DIR: 项目目录路径

    \b
    示例:
      python main.py chat ./my_app
    """
    model = ctx.obj['model']
    url = ctx.obj['url']
    verbose_events = ctx.obj['verbose_events']

    _start_command_event_log("chat", project_dir, verbose_events)

    # 打印标题
    if RICH_AVAILABLE:
        console.print(Panel.fit(
            "[bold magenta]自主编程助手 Agent[/bold magenta]\n"
            "[dim]交互式对话模式[/dim]\n"
            "[dim]输入 'exit' 或 'quit' 退出[/dim]",
            border_style="magenta"
        ))
    else:
        print("\n" + "="*50)
        print("自主编程助手 Agent - 交互式对话模式")
        print("输入 'exit' 或 'quit' 退出")
        print("="*50 + "\n")

    # 创建 Agent 实例
    try:
        agent = CodingAgent(
            project_dir=project_dir,
            model_name=model,
            base_url=url
        )
    except Exception as e:
        if RICH_AVAILABLE:
            console.print(f"[red]错误: 创建 Agent 失败 - {str(e)}[/red]")
        else:
            print(f"错误: 创建 Agent 失败 - {str(e)}")
        sys.exit(1)

    # 对话循环
    chat_history = []

    while True:
        try:
            # 获取用户输入
            if RICH_AVAILABLE:
                user_input = console.input("[bold blue]你:[/bold blue] ")
            else:
                user_input = input("你: ")

            # 检查退出命令
            if user_input.lower() in ('exit', 'quit', 'q'):
                if RICH_AVAILABLE:
                    console.print("[dim]再见！[/dim]")
                else:
                    print("再见！")
                _end_command_event_log("chat", True, "聊天会话正常结束")
                break

            # 跳过空输入
            if not user_input.strip():
                continue

            # 发送消息给 Agent
            if RICH_AVAILABLE:
                console.print("[dim]Agent 正在思考...[/dim]")
            else:
                print("Agent 正在思考...")

            response = agent.chat(user_input, chat_history)

            # 更新对话历史（使用 LangChain 兼容格式）
            # MessagesPlaceholder 期望元组格式: ("role", "content")
            chat_history.append(("human", user_input))
            chat_history.append(("ai", response))

            # 显示回复
            if RICH_AVAILABLE:
                console.print(f"\n[bold green]Agent:[/bold green]")
                console.print(Markdown(response))
                console.print()
            else:
                print(f"\nAgent: {response}\n")

        except KeyboardInterrupt:
            if RICH_AVAILABLE:
                console.print("\n[dim]已中断[/dim]")
            else:
                print("\n已中断")
            _end_command_event_log("chat", True, "聊天会话被用户中断")
            break
        except Exception as e:
            if RICH_AVAILABLE:
                console.print(f"[red]错误: {str(e)}[/red]")
            else:
                print(f"错误: {str(e)}")
            emit_event(
                event_type="error",
                component="cli",
                name="chat",
                payload={"message": str(e)},
                ok=False,
                phase="chat"
            )


# ============================================
# add-feature 命令 - 添加功能
# ============================================

@cli.command('add-feature')
@click.argument('project_dir', type=click.Path(exists=True))
@click.option('--id', 'feature_id', required=True, help='功能 ID（如 feat-001）')
@click.option('--name', '-n', required=True, help='功能名称')
@click.option('--desc', '-d', default='', help='功能描述')
@click.option('--priority', '-p', default='medium', type=click.Choice(['high', 'medium', 'low']), help='优先级')
@click.option('--verify', 'verify_commands', multiple=True, help='验收命令（可多次传入）')
@click.pass_context
def add_feature(ctx, project_dir, feature_id, name, desc, priority, verify_commands):
    """
    添加新功能到项目

    PROJECT_DIR: 项目目录路径

    \b
    示例:
      python main.py add-feature ./my_app --id feat-005 --name "用户登录" --priority high
      python main.py add-feature ./my_app --id feat-006 --name "导出报告" --verify "python -m pytest -q"
    """
    progress_manager = ProgressManager(project_dir)

    success = progress_manager.add_feature(
        feature_id=feature_id,
        name=name,
        description=desc,
        priority=priority,
        verify_commands=list(verify_commands) if verify_commands else None
    )

    if success:
        if RICH_AVAILABLE:
            console.print(f"[green]✓ 功能 '{name}' 已添加[/green]")
        else:
            print(f"✓ 功能 '{name}' 已添加")
        _end_command_event_log("add-feature", True, f"功能已添加: {feature_id}")
    else:
        if RICH_AVAILABLE:
            console.print(f"[red]✗ 添加功能失败[/red]")
        else:
            print("✗ 添加功能失败")
        _end_command_event_log("add-feature", False, f"功能添加失败: {feature_id}")


# ============================================
# 程序入口
# ============================================

if __name__ == '__main__':
    """
    程序主入口

    解析命令行参数并执行对应的命令。
    """
    try:
        cli()
    except Exception as e:
        if RICH_AVAILABLE:
            console.print(f"[red]错误: {str(e)}[/red]")
        else:
            print(f"错误: {str(e)}")
        sys.exit(1)
    _start_command_event_log("status", project_dir, ctx.obj['verbose_events'])
    _start_command_event_log("add-feature", project_dir, ctx.obj['verbose_events'])
