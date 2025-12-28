"""DeepCodeResearch 主入口文件"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

# ⚠️ 应用编码补丁（修复历史保存路径和编码问题）
# 所有平台都需要应用，因为需要修复 session_id 路径
try:
    from src.utils.encoding_patch import apply_encoding_patch
    apply_encoding_patch()
except Exception as e:
    print(f"[警告] 编码补丁应用失败: {e}")

from ms_agent.config import Config
from ms_agent.utils import get_logger

from src.workflows.deepcode_workflow import DeepCodeResearchWorkflow

logger = get_logger()

# ⚠️ 注册自定义 Memory 到 ms-agent（遵循配置驱动原则）
# 使用 DeepCodeMemory（基于 mem0ai：https://github.com/mem0ai/mem0）
# 在 YAML 配置中使用 `deepcode_memory`
try:
    from src.agents.mixins import register_deepcode_memory
    register_deepcode_memory()
except Exception as e:
    logger.warning(f"[警告] 注册 deepcode_memory 失败: {e}")


async def run_workflow(
    query: str | None = None,
    files: list | None = None,
    session_id: str | None = None,
) -> dict:
    """运行工作流
    
    Args:
        query: 用户查询
        files: 文件列表（可选）
        session_id: 会话 ID（可选）
    
    Returns:
        工作流执行结果
    """
    if not query or not query.strip():
        logger.warning(f"run_workflow 调用时未提供 query，跳过执行")
        return {
            "status": "IDLE",
            "message": "未提供有效的指令，已跳过执行。",
            "final_output": "",
        }

    workflow_config = os.getenv("WORKFLOW_CONFIG", "src/config/workflow.yaml")
    trust_remote_code = os.getenv("TRUST_REMOTE_CODE", "true").lower() == "true"

    # Fix: Ensure llm_base_url is available before loading workflow config
    # This fixes KeyError: 'llm_base_url' in ms-agent config._update_config()
    # ms-agent's _update_config() checks for exact key match, so we need both lowercase and uppercase
    modelscope_base_url = os.getenv('MODELSCOPE_BASE_URL')
    if modelscope_base_url:
        os.environ['LLM_BASE_URL'] = modelscope_base_url
        os.environ['llm_base_url'] = modelscope_base_url  # 小写键名，用于 <llm_base_url> 占位符
        logger.debug(f'[main] 设置 LLM_BASE_URL = {modelscope_base_url} (大小写)')
    
    modelscope_api_key = os.getenv('MODELSCOPE_API_KEY')
    if modelscope_api_key:
        os.environ['LLM_API_KEY'] = modelscope_api_key
        os.environ['llm_api_key'] = modelscope_api_key  # 小写键名
        logger.debug('[main] 设置 LLM_API_KEY (大小写)')

    logger.info(f"从 {workflow_config} 加载工作流配置")
    import sys as sys_module
    _argv = sys_module.argv[:]
    try:
        sys_module.argv = [sys_module.argv[0]]
        config = Config.from_task(workflow_config)
    finally:
        sys_module.argv = _argv

    workflow = DeepCodeResearchWorkflow(
        config=config,
        trust_remote_code=trust_remote_code,
    )

    logger.info("启动 DeepCodeResearchWorkflow...")
    
    # 构建输入（支持 query + files）
    inputs = {"query": query.strip()}
    if files:
        inputs["files"] = files
    if session_id:
        inputs["session_id"] = session_id
    
    result = await workflow.run(inputs)
    logger.info("工作流完成")
    status = result.get('status', 'UNKNOWN') if isinstance(result, dict) else 'UNKNOWN'
    logger.info(f"[workflow-result] status={status}")
    return result


def prepare_session() -> str:
    """预创建 session 目录，让用户可以上传文件
    
    Returns:
        session_id
    """
    # 生成 session_id
    session_id = uuid.uuid4().hex[:12]
    
    # 获取输出目录
    output_dir = os.getenv("OUTPUT_DIR", "output")
    session_dir = Path(output_dir) / session_id
    
    # 创建所需目录
    uploads_dir = session_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    
    # 也创建其他常用目录
    (session_dir / "repo").mkdir(parents=True, exist_ok=True)
    (session_dir / "spec_kit").mkdir(parents=True, exist_ok=True)
    (session_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    
    return session_id


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="DeepCodeResearch - 智能代码生成系统")
    parser.add_argument("--query", nargs="?", help="要生成的项目描述或任务", default=os.getenv("WORKFLOW_QUERY"))
    parser.add_argument("query_positional", nargs="*", help="也可以直接作为位置参数传入任务描述")
    parser.add_argument("--config", help="工作流配置文件路径", default=os.getenv("WORKFLOW_CONFIG", "src/config/workflow.yaml"))
    parser.add_argument("--prepare", action="store_true", help="预创建 session 目录（用于上传文件）")
    parser.add_argument("--session-id", dest="session_id", help="使用已存在的 session ID")
    
    args = parser.parse_args()
    
    # 处理 --prepare 模式：只创建目录，不执行工作流
    if args.prepare:
        session_id = prepare_session()
        output_dir = os.getenv("OUTPUT_DIR", "output")
        uploads_path = Path(output_dir) / session_id / "uploads"
        
        print("\n" + "=" * 60)
        print(" Session 已创建")
        print("=" * 60)
        print(f"\n  Session ID: {session_id}")
        print(f"  上传目录:   {uploads_path.absolute()}")
        print("\n  请将 PDF、DOCX 等文件放入上传目录，然后运行：")
        print(f"\n  python -m src.main --session-id {session_id} \"你的任务描述\"")
        print("\n" + "=" * 60)
        return
    
    # 优先使用位置参数，其次是 --query 参数（包含环境变量默认值）
    query = (" ".join(args.query_positional).strip() if args.query_positional else None) or args.query
    
    if not query:
        print(" 错误: 请提供任务描述 (通过命令行参数或 WORKFLOW_QUERY 环境变量)")
        print("\n 提示: 如果需要上传文件，请先运行: python -m src.main --prepare")
        sys.exit(1)

    # 设置配置文件路径环境变量，供 run_workflow 使用
    os.environ["WORKFLOW_CONFIG"] = args.config
    
    # 如果指定了 session_id，设置环境变量
    if args.session_id:
        os.environ["SESSION_ID"] = args.session_id
        logger.info(f"使用已存在的 Session: {args.session_id}")

    try:
        result = asyncio.run(
            run_workflow(
                query=query,
                session_id=args.session_id
            )
        )
        
        # 格式化输出结果
        print("\n" + "="*50)
        print(" 工作流执行完成")
        print("="*50)
        
        if isinstance(result, dict):
            print(f"状态: {result.get('status', 'UNKNOWN')}")
            
            final_output = result.get('final_output', '')
            if final_output:
                print("\n 最终输出:")
                print("-" * 20)
                print(final_output[:1000] + ("..." if len(final_output) > 1000 else ""))
                print("-" * 20)
        else:
            print(f"结果: {result}")
        
    except KeyboardInterrupt:
        print("\n 用户取消执行")
        sys.exit(130)
    except Exception as e:
        print(f"\n 执行出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
