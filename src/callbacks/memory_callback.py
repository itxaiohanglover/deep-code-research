# Copyright (c) Deep Code Research. All rights reserved.
"""记忆保存回调：在 Agent 执行完成后自动保存对话到记忆

核心功能：
1. 在 Agent 执行完成后，将完整对话保存到 mem0
2. mem0 会自动使用 LLM 提取关键事实和生成摘要
3. 保存的记忆可被同一 Agent 在后续迭代中语义检索

性能优化：
- 只在关键 Agent 保存记忆（coding, testing, reflecting）
- 跳过研究阶段 Agent（避免不必要的 LLM 调用）
- 使用标志防止重复保存

使用方法：
在 Agent 的 YAML 配置中添加：
```yaml
callbacks:
  - callbacks/memory_callback
```
"""

from typing import List, Optional, Set

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger
from omegaconf import DictConfig

from src.memory.deepcode_memory import DeepCodeMemoryManager
from src.utils.workflow_manager import workflow_manager

logger = get_logger()

# 需要保存记忆的 Agent（只有这些 Agent 会被 reflecting 回退到）
# 根据 reflecting.py 的 next_step() 方法：
# - phase2（设计缺陷）→ 回退到 requirements（Analysis 阶段）
# - phase3（实现缺陷）→ 回退到 coding  
# - testing（无测试）→ 回退到 testing
# 这些 Agent 需要记忆来"意识到自己的问题并重构想法"
MEMORY_ENABLED_AGENTS: Set[str] = {
    'requirements',  # 回退目标：设计缺陷(phase2)时回退，需要重新分析需求
    'coding',        # 回退目标：实现缺陷(phase3)时回退，需要修复代码
    'testing',       # 回退目标：无测试时回退，需要重新生成测试
    # 注意：
    # - reflecting 不是回退目标，它是决策者
    # - planning 不是回退目标，设计缺陷直接回退到 requirements
}


class MemoryCallback(Callback):
    """记忆保存回调
    
    职责：
    1. 在 Agent 执行完成后，将对话内容保存到 DeepCodeMemory
    2. mem0 自动提取关键事实和生成摘要（通过 LLM）
    3. 支持按 agent_id 隔离，每个 Agent 只能检索自己的记忆
    
    性能优化：
    - 只在关键 Agent 保存记忆（避免不必要的 LLM 调用）
    - 使用标志防止重复保存
    
    记忆存储结构：
    - user_id: 项目 ID（session_id）
    - agent_id: Agent 名称（config.tag）
    - metadata: {iteration, step, ...}
    - content: 原始对话内容（mem0 自动提取摘要）
    """
    
    def __init__(self, config: DictConfig):
        """初始化回调"""
        super().__init__(config)
        self._memory = None
        self._initialized = False
        self._saved_this_task = False  # 防止同一任务重复保存
    
    def _get_memory(self):
        """懒加载获取记忆实例"""
        if not self._initialized:
            try:
                self._memory = DeepCodeMemoryManager.get_memory(self.config)
                self._initialized = True
                logger.debug("[MemoryCallback] 记忆模块初始化成功")
            except Exception as e:
                logger.warning(f"[MemoryCallback] 记忆模块初始化失败: {e}")
                self._initialized = True  # 标记已尝试，避免重复尝试
        return self._memory
    
    def _should_save_memory(self, agent_id: str) -> bool:
        """判断是否应该为该 Agent 保存记忆
        
        优化策略：只为关键 Agent 保存记忆，避免不必要的 LLM 调用
        - 研究阶段 Agent 的输出已经保存到 artifacts，不需要额外保存记忆
        - 只有代码生成、测试、反思等关键阶段需要记忆来支持迭代优化
        """
        if not agent_id:
            return False
        
        # 精确匹配
        if agent_id in MEMORY_ENABLED_AGENTS:
            return True
        
        # 模糊匹配（处理带后缀的情况，如 coding_1）
        agent_base = agent_id.split('_')[0].lower()
        return agent_base in MEMORY_ENABLED_AGENTS
    
    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        """任务开始时重置保存标志"""
        self._saved_this_task = False
    
    async def on_task_end(self, runtime: Runtime, messages: List[Message]):
        """任务结束时保存对话到记忆
        
        步骤：
        1. 检查是否需要保存（只有关键 Agent 需要）
        2. 获取 Agent 标识（agent_id）
        3. 构建对话内容
        4. 保存到 mem0（mem0 自动提取摘要）
        """
        # 防止同一任务重复保存
        if self._saved_this_task:
            return
        
        # 1. 获取 Agent 标识
        agent_id = getattr(runtime, 'tag', None) if runtime else None
        if not agent_id:
            logger.debug("[MemoryCallback] 无法获取 agent_id，跳过保存")
            return
        
        # 2. 检查是否需要保存（性能优化：只为关键 Agent 保存）
        if not self._should_save_memory(agent_id):
            logger.debug(f"[MemoryCallback] [{agent_id}] 非关键 Agent，跳过记忆保存")
            return
        
        memory = self._get_memory()
        if not memory:
            logger.debug("[MemoryCallback] 记忆模块未初始化，跳过保存")
            return
        
        # 3. 构建对话内容（传给 mem0，由 mem0 自动提取摘要）
        conversation_content = self._build_conversation_content(messages)
        if not conversation_content:
            logger.debug(f"[MemoryCallback] [{agent_id}] 无有效对话内容，跳过保存")
            return
        
        # 4. 保存到 mem0（mem0 会自动调用 LLM 提取关键事实）
        try:
            iteration = workflow_manager.get_iteration() or 1
            step = workflow_manager.get_step() or agent_id
            
            metadata = {
                'iteration': iteration,
                'step': step,
                'agent_tag': agent_id,
            }
            
            # mem0.add() 会自动：
            # 1. 调用 LLM 提取关键事实（使用 custom_fact_extraction_prompt）
            # 2. 向量化存储
            # 3. 建立索引
            result = memory.add(
                content=conversation_content,
                agent_id=agent_id,
                metadata=metadata,
                iteration=iteration
            )
            
            self._saved_this_task = True  # 标记已保存
            
            if result:
                # 获取 mem0 提取的记忆数量
                memories_added = len(result.get('results', [])) if isinstance(result, dict) else 1
                logger.info(f"[MemoryCallback] [{agent_id}] ✅ mem0 已提取并保存 {memories_added} 条记忆 (iteration={iteration})")
            else:
                logger.warning(f"[MemoryCallback] [{agent_id}] ⚠️ 保存记忆失败（mem0 未返回结果）")
                
        except Exception as e:
            logger.error(f"[MemoryCallback] [{agent_id}] 保存记忆出错: {e}")
    
    def _build_conversation_content(self, messages: List[Message]) -> Optional[str]:
        """构建对话内容
        
        将消息列表转换为结构化文本，供 mem0 提取事实
        
        格式：
        User: xxx
        Assistant: xxx
        """
        if not messages:
            return None
        
        parts = []
        for msg in messages:
            role = getattr(msg, 'role', 'unknown')
            content = getattr(msg, 'content', '')
            
            # 处理不同类型的 content
            if isinstance(content, list):
                # content 可能是 [{"type": "text", "text": "..."}] 格式
                texts = []
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'text':
                        texts.append(item.get('text', ''))
                    elif isinstance(item, str):
                        texts.append(item)
                content = '\n'.join(texts)
            
            if content:
                # 限制每条消息长度，避免过长
                if len(content) > 2000:
                    content = content[:2000] + "...(truncated)"
                
                role_label = "User" if role == "user" else "Assistant" if role == "assistant" else role.capitalize()
                parts.append(f"{role_label}: {content}")
        
        return "\n\n".join(parts) if parts else None

