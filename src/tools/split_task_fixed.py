"""自定义 SplitTask 工具

覆盖 ms-agent 的 SplitTask，让子任务使用 BaseAgent（包含 RAGMixin）。

设计思路：
1. 继承原始的 SplitTask 类
2. 覆盖 call_tool 方法
3. 创建子任务时使用 BaseAgent 而不是 LLMAgent
4. 这样子任务也能享受 RAGMixin 的 bug 修复
5. 修复了事件循环嵌套问题
"""

import asyncio

from ms_agent.tools.split_task import SplitTask as OriginalSplitTask
from ms_agent.utils.utils import escape_yaml_string
from omegaconf import DictConfig
from ms_agent.utils import get_logger

logger = get_logger()


class SplitTask(OriginalSplitTask):
    """修复版 SplitTask 工具
    
    修复内容：
    - 使用 BaseAgent（包含 RAGMixin）创建子任务，而不是原始的 LLMAgent
    - 这样子任务也能享受 RAGMixin 对 rag_mapping bug 的修复
    - 修复了事件循环嵌套问题
    """

    async def call_tool(self, server_name: str, *, tool_name: str,
                        tool_args: dict):
        """
        覆盖父类方法，使用 BaseAgent 创建子任务
        
        1. BaseAgent (包含 RAGMixin) 用于启动子任务
        2. config 从父任务继承
        3. 支持并行和顺序执行模式
        4. 修复了事件循环嵌套问题
        """
        # 导入 BaseAgent 而不是 LLMAgent
        from src.agents._base_agent import BaseAgent

        tasks = tool_args.get('tasks')
        execution_mode = tool_args.get(
            'execution_mode', 'sequential')
        
        # 获取父任务的 tag（用于日志）
        parent_tag = getattr(self.config, 'tag', 'split_task')

        async def run_agent_async(i, task):
            """异步执行单个子任务"""
            system = task['system']
            query = task['query']
            config = DictConfig(self.config)
            if not hasattr(config, 'prompt'):
                config.prompt = DictConfig({})
            config.prompt.system = escape_yaml_string(system)
            
            trust_remote_code = getattr(config, 'trust_remote_code', False)
            
            # 创建一个简单的 Agent 类，实现 _build_prompt 方法
            class SubTaskAgent(BaseAgent):
                """子任务专用 Agent，使用配置中的 system prompt"""
                
                def _build_prompt(self, user_input: str) -> str:
                    """直接返回用户输入，system prompt 已在配置中"""
                    return user_input
            
            # 使用 SubTaskAgent 而不是直接使用 BaseAgent
            agent = SubTaskAgent(
                config=config,
                trust_remote_code=trust_remote_code,
                tag=f'{config.tag}-r{self.round}-{self.tag_prefix}{i}',
                load_cache=getattr(config, 'load_cache', False))

            # 直接调用 await，不创建新的事件循环
            return await agent.run(query)

        result = []
        if execution_mode == 'parallel':
            # 并行执行所有任务
            task_futures = [run_agent_async(i, task) for i, task in enumerate(tasks)]
            task_results = await asyncio.gather(*task_futures, return_exceptions=True)
            
            for i, task_result in enumerate(task_results):
                if isinstance(task_result, Exception):
                    logger.error(
                        f'{parent_tag}-{self.tag_prefix}{i} failed with error: {task_result}'
                    )
                    result.append({
                        'task_index': i,
                        'error': str(task_result)
                    })
                else:
                    result.append({
                        'task_index': i,
                        'result': task_result
                    })
        else:
            # 顺序执行任务
            for i, task in enumerate(tasks):
                try:
                    task_result = await run_agent_async(i, task)
                    result.append({'task_index': i, 'result': task_result})
                except Exception as e:
                    logger.error(
                        f'{parent_tag}-{self.tag_prefix}{i} failed with error: {e}'
                    )
                    result.append({'task_index': i, 'error': str(e)})

        self.round += 1
        return result
