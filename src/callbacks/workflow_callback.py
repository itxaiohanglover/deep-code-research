"""通用工作流回调：日志打印和输入输出处理（简化版，移除 progress_callback）"""

from typing import List, Dict, Any
import time

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

from src.utils.workflow_manager import workflow_manager

logger = get_logger()


class WorkflowCallback(Callback):
    """通用工作流回调，负责日志打印
    
    设计原则：
    1. 只负责日志打印，不处理前端进度更新
    2. 前端进度更新应该通过其他机制（WebSocket、事件总线等）实现
    3. 遵循 ms-agent 的 Callback 最佳实践
    """

    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.started_at = time.time()

    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        """任务开始时调用：打印日志"""
        self.started_at = time.time()
        
        # 动态获取 workflow 信息
        current_step = workflow_manager.get_step()
        current_iteration = workflow_manager.get_iteration()
        
        # 打印清晰的分隔线和标题
        separator = "=" * 80
        logger.info(separator)
        logger.info(f" [{current_step.upper()}] Agent 开始执行 (迭代 {current_iteration})")
        logger.info(separator)
        
        # 打印输入信息（已禁用）
        # if messages:
        #     user_messages = [msg for msg in messages if msg.role == "user"]
        #     if user_messages:
        #         content = user_messages[-1].content
        #         input_preview = f"{content[:200]}..." if len(content) > 200 else content
        #         logger.info(f" 输入: {input_preview}")

    async def on_tool_call(self, runtime: Runtime, messages: List[Message]):
        """调用工具前调用：打印工具调用信息"""
        current_step = workflow_manager.get_step()
        
        # 提取工具调用信息
        tool_calls = self._extract_tool_calls_from_messages(messages)
        
        if tool_calls:
            for tool_call in tool_calls:
                tool_name = tool_call.get("name", "unknown")
                logger.info(f" 工具调用: {tool_name}")

    async def after_tool_call(self, runtime: Runtime, messages: List[Message]):
        """调用工具后调用：打印工具调用结果"""
        current_step = workflow_manager.get_step()
        
        # 提取工具调用结果
        tool_results = self._extract_tool_results_from_messages(messages)
        
        if tool_results:
            for tool_result in tool_results:
                tool_name = tool_result.get("name", "unknown")
                result_content = tool_result.get("result", "")
                result_preview = f"{result_content[:100].replace(chr(10), ' ')}..." if len(result_content) > 100 else result_content.replace(chr(10), ' ')
                logger.info(f"工具完成: {tool_name} -> {result_preview}")

    async def on_task_end(self, runtime: Runtime, messages: List[Message]):
        """任务完成时调用：打印最终输出"""
        duration = time.time() - self.started_at
        
        current_step = workflow_manager.get_step()
        current_iteration = workflow_manager.get_iteration()
        
        # 提取输出内容
        output_content = self._extract_output(messages)
        
        # 输出预览（前200个字符）（已禁用）
        # if output_content:
        #     output_preview = f"{output_content[:200].replace(chr(10), ' ')}..." if len(output_content) > 200 else output_content.replace(chr(10), ' ')
        #     logger.info(f"输出预览: {output_preview}")
        
        # 打印完成信息
        separator = "=" * 80
        logger.info(f" [{current_step.upper()}] Agent 完成 (耗时: {duration:.2f}秒)")
        logger.info(separator)
        logger.info("")  # 空行分隔

    async def on_generate_response(self, runtime: Runtime, messages: List[Message]):
        """在调用 LLM 前调用：打印准备消息"""
        current_step = workflow_manager.get_step()
        logger.debug(f"[{current_step}] 准备调用 LLM 生成响应")

    # ------------------------------------------------------------------ #
    # Helper methods
    # ------------------------------------------------------------------ #
    
    def _extract_output(self, messages: List[Message]) -> str:
        """从消息中提取输出内容"""
        for msg in reversed(messages):
            if isinstance(msg, Message) and msg.role == "assistant" and msg.content:
                return msg.content.strip()
        return ""

    def _extract_tool_calls_from_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """从消息中提取工具调用信息"""
        tool_calls = []
        for msg in messages:
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    tool_info = {}
                    
                    # 处理不同的 tool_call 格式
                    if hasattr(tool_call, 'function'):
                        func = tool_call.function
                        tool_info = {
                            "id": getattr(tool_call, 'id', None),
                            "name": getattr(func, 'name', 'unknown'),
                            "arguments": getattr(func, 'arguments', ''),
                        }
                    elif isinstance(tool_call, dict):
                        func = tool_call.get('function', {})
                        tool_info = {
                            "id": tool_call.get('id', None),
                            "name": func.get('name', 'unknown') if isinstance(func, dict) else 'unknown',
                            "arguments": func.get('arguments', '') if isinstance(func, dict) else '',
                        }
                    
                    if tool_info.get("name") != 'unknown':
                        tool_calls.append(tool_info)
        
        return tool_calls

    def _extract_tool_results_from_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """从消息中提取工具调用结果"""
        tool_results = []
        
        # 收集所有工具调用
        tool_call_map = {}  # {tool_call_id: tool_info}
        for msg in messages:
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    tool_id = None
                    tool_name = 'unknown'
                    
                    if hasattr(tool_call, 'id'):
                        tool_id = tool_call.id
                    elif isinstance(tool_call, dict):
                        tool_id = tool_call.get('id')
                    
                    if hasattr(tool_call, 'function'):
                        func = tool_call.function
                        tool_name = getattr(func, 'name', 'unknown')
                    elif isinstance(tool_call, dict):
                        tool_name = tool_call.get('function', {}).get('name', 'unknown')
                    
                    if tool_id:
                        tool_call_map[tool_id] = {"name": tool_name}
        
        # 收集所有工具结果
        for msg in messages:
            # 兼容不同的 tool result 格式
            is_tool_msg = (hasattr(msg, 'role') and msg.role == "tool") or (isinstance(msg, dict) and msg.get('role') == 'tool')
            
            if is_tool_msg:
                tool_call_id = None
                result_content = ''
                tool_name = 'unknown'
                
                # 获取 tool_call_id
                if hasattr(msg, 'tool_call_id'):
                    tool_call_id = msg.tool_call_id
                elif isinstance(msg, dict):
                    tool_call_id = msg.get('tool_call_id')
                
                # 获取 content
                if hasattr(msg, 'content'):
                    result_content = msg.content or ''
                elif isinstance(msg, dict):
                    result_content = msg.get('content', '')
                
                # 获取 tool_name (如果 Message 中直接携带了 name 属性)
                if hasattr(msg, 'name'):
                    tool_name = msg.name
                elif isinstance(msg, dict):
                    tool_name = msg.get('name')
                
                # 如果 Message 中没有 name，尝试从 map 中查找
                if (not tool_name or tool_name == 'unknown') and tool_call_id and tool_call_id in tool_call_map:
                    tool_name = tool_call_map[tool_call_id]["name"]
                
                if tool_call_id or result_content: # 只要有内容就记录
                    tool_results.append({
                        "id": tool_call_id or "unknown",
                        "name": tool_name,
                        "result": str(result_content)[:1000] + "..." if len(str(result_content)) > 1000 else str(result_content),
                    })
        
        return tool_results