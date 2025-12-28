"""Agent 基类

提供统一的 Agent 代码模式，确保所有 Agent 使用相同的结构。

设计原则：
1. 所有 Agent 继承 BaseAgent，减少代码重复
2. BaseAgent 继承 LLMAgent, ArtifactStoreMixin, RAGMixin
3. 统一使用 _build_prompt 方法构建提示词
4. 子类可以重写 run 方法添加额外逻辑
5. 支持产物依赖声明，自动收集前序产物
6. Memory 通过配置驱动，使用 register_deepcode_memory() 注册自定义 Memory
7. 支持 LLM 调用缓存，避免相同 prompt 重复调用（可配置）
"""

import os
from typing import Union, Dict, List, ClassVar, Optional
from ms_agent.llm.utils import Message

from ms_agent.agent.llm_agent import LLMAgent
from ms_agent.utils import get_logger

from src.agents.mixins import ArtifactStoreMixin, RAGMixin
from src.agents.types import AgentInput, AgentOutput, ArtifactDict
from src.utils.llm_cache import llm_cache

logger = get_logger()


class BaseAgent(RAGMixin, LLMAgent, ArtifactStoreMixin):
    """Agent 基类
    
    职责：
    1. 提供统一的 Agent 代码模式
    2. 统一处理提示词构建和执行
    3. 自动收集前序产物（通过 ARTIFACT_DEPENDENCIES 声明）
    4. 统一日志记录格式
    5. 支持 LLM 调用缓存（通过 ENABLE_CACHE 配置）
    
    产物依赖声明：
    子类可以通过类属性 ARTIFACT_DEPENDENCIES 声明依赖的前序产物：
    
        class MyAgent(BaseAgent):
            ARTIFACT_DEPENDENCIES = ["requirements", "tech_research"]
            
            def _build_prompt(self, user_input: str) -> str:
                artifacts = self._get_artifacts()  # 自动收集声明的产物
                return build_prompt(user_input, **artifacts)
    
    统一模式：
    1. 继承顺序: RAGMixin, LLMAgent, ArtifactStoreMixin
    2. 通过 ARTIFACT_DEPENDENCIES 声明依赖产物
    3. 使用 _get_artifacts() 获取产物字典
    4. 实现 _build_prompt 方法构建提示词
    
    Mixin 功能：
    1. RAGMixin: RAG 初始化和检索
    2. ArtifactStoreMixin: 产物存储访问
    
    缓存功能：
    - 默认启用，可通过 ENABLE_CACHE = False 禁用
    - 可通过环境变量 LLM_CACHE_ENABLED=false 全局禁用
    - 缓存基于 prompt + model 的 hash 值
    
    使用示例：
        class MyAgent(BaseAgent):
            ARTIFACT_DEPENDENCIES = ["requirements", "architecture"]
            ENABLE_CACHE = True  # 默认启用缓存
            
            def _build_prompt(self, user_input: str) -> str:
                artifacts = self._get_artifacts()
                return build_my_prompt(
                    user_input=user_input,
                    requirements=artifacts.get("requirements"),
                    architecture=artifacts.get("architecture")
                )
    """
    
    # 子类可以覆盖此属性声明依赖的前序产物
    ARTIFACT_DEPENDENCIES: ClassVar[List[str]] = []
    
    # 子类可以覆盖此属性控制是否启用缓存（默认启用）
    ENABLE_CACHE: ClassVar[bool] = True
    
    def _get_artifacts(self) -> ArtifactDict:
        """获取声明的前序产物
        
        根据 ARTIFACT_DEPENDENCIES 自动收集产物。
        
        Returns:
            产物字典，key 为产物名称，value 为产物内容
        """
        artifacts: ArtifactDict = {}
        for name in self.ARTIFACT_DEPENDENCIES:
            content = self._get_previous_artifact(name, default="")
            artifacts[name] = content
            if content:
                logger.debug(f"[{self.tag}] 获取产物 {name}: {len(content)} 字符")
        return artifacts
    
    def _build_prompt(self, user_input: str) -> str:
        """构建提示词（子类必须实现）
        
        Args:
            user_input: 用户输入
            
        Returns:
            构建后的提示词
        """
        raise NotImplementedError("子类必须实现 _build_prompt 方法")
    
    def _prepare_inputs(self, inputs: AgentInput) -> AgentInput:
        """预处理输入，应用 _build_prompt
        
        Args:
            inputs: 输入（字符串或 Message 列表）
            
        Returns:
            处理后的输入
        """
        if isinstance(inputs, str):
            # 如果输入是字符串，直接调用 _build_prompt
            return self._build_prompt(inputs)
        elif isinstance(inputs, list) and inputs:
            # 如果输入是 Message 列表，处理最后一条用户消息
            from dataclasses import asdict
            for msg in reversed(inputs):
                if isinstance(msg, Message) and msg.role == 'user':
                    # 调用 _build_prompt 处理用户消息内容
                    msg_dict = asdict(msg)
                    msg_dict['content'] = self._build_prompt(msg.content)
                    processed_msg = Message(**msg_dict)
                    # 创建新的消息列表，替换最后一条用户消息
                    msg_index = inputs.index(msg)
                    return inputs[:msg_index] + [processed_msg] + inputs[msg_index+1:]
            
            # 如果 Message 列表中没有 user 消息，从 assistant 消息中提取内容构建 prompt
            # 这种情况发生在 workflow 传递上一个 agent 的输出时
            logger.warning(f"[{self.tag}] 输入消息列表中无 user 消息，从 assistant 消息构建")
            for msg in reversed(inputs):
                if isinstance(msg, Message) and msg.role == 'assistant' and msg.content:
                    # 使用 assistant 消息内容作为上下文
                    return self._build_prompt(msg.content)
            
            # 如果也没有 assistant 消息，返回空 prompt
            logger.warning(f"[{self.tag}] 无法从消息列表提取有效内容，使用空输入")
            return self._build_prompt("")
        
        # 其他情况（None 或空列表），使用空输入
        logger.warning(f"[{self.tag}] 输入为空，使用空输入")
        return self._build_prompt("")
    
    def log_output(self, content: str):
        """重写 log_output 方法，关闭 Agent 的输入输出日志
        
        注意：此方法覆盖了 LLMAgent 的 log_output 方法，用于关闭控制台中的
        Agent 输入输出日志（如 [user]:、[assistant]:、[tool_calling]: 等）。
        其他重要日志（如错误日志）不受影响。
        
        如需完全关闭所有输出（包括流式输出），请在配置文件中设置：
        generation_config:
          stream: false
        
        Args:
            content (str): 要输出的内容（此方法中不做任何处理）
        """
        # 不输出任何内容，静默处理
        pass
    
    def _should_use_cache(self) -> bool:
        """判断是否应该使用缓存
        
        条件：
        1. 类属性 ENABLE_CACHE 为 True
        2. 全局缓存已启用
        3. 环境变量未禁用缓存
        
        Returns:
            是否使用缓存
        """
        # 类级别禁用
        if not self.ENABLE_CACHE:
            return False
        
        # 全局禁用（环境变量）
        env_enabled = os.getenv("LLM_CACHE_ENABLED", "true").lower()
        if env_enabled in ("false", "0", "no"):
            return False
        
        # 检查全局缓存实例
        return llm_cache.enabled
    
    def _get_model_name(self) -> str:
        """获取当前使用的模型名称
        
        Returns:
            模型名称
        """
        # 尝试从配置中获取模型名称
        if hasattr(self, 'config') and self.config:
            llm_config = getattr(self.config, 'llm', None)
            if llm_config:
                return getattr(llm_config, 'model', 'unknown')
        return 'unknown'
    
    def _extract_result_content(self, result: AgentOutput) -> str:
        """从结果中提取内容（用于缓存）
        
        Args:
            result: Agent 输出
            
        Returns:
            提取的内容字符串
        """
        if isinstance(result, list):
            for msg in reversed(result):
                if isinstance(msg, Message) and msg.role == 'assistant' and msg.content:
                    return msg.content
        return ""
    
    def _create_cached_result(self, content: str) -> AgentOutput:
        """从缓存内容创建结果
        
        Args:
            content: 缓存的内容
            
        Returns:
            Agent 输出
        """
        return [Message(role='assistant', content=content)]
    
    async def run(self, inputs: AgentInput, **kwargs) -> AgentOutput:
        """运行 Agent（统一模式，支持缓存）
        
        步骤：
        1. 记录开始日志
        2. 预处理输入（应用 _build_prompt）
        3. 检查缓存（如果启用）
        4. 缓存命中则直接返回
        5. 缓存未命中则调用 LLM
        6. 保存结果到缓存
        7. 返回结果
        
        Args:
            inputs: 输入（字符串或 Message 列表）
            **kwargs: 其他参数
            
        Returns:
            Message 列表
        
        注意：
            - 子类可以重写此方法添加额外逻辑
            - 重写时建议先调用 super().run() 获取基础结果
            - 缓存基于处理后的 prompt，相同 prompt 会返回缓存结果
        """
        logger.info(f"[{self.tag}] 开始执行")
        
        # 预处理输入（应用 _build_prompt）
        processed_inputs = self._prepare_inputs(inputs)
        
        # 获取用于缓存的 prompt 字符串
        cache_key_prompt = ""
        if isinstance(processed_inputs, str):
            cache_key_prompt = processed_inputs
        elif isinstance(processed_inputs, list):
            # 从消息列表中提取 user 消息作为缓存 key
            for msg in reversed(processed_inputs):
                if isinstance(msg, Message) and msg.role == 'user' and msg.content:
                    cache_key_prompt = msg.content
                    break
        
        # 检查缓存（如果启用且有有效的缓存 key）
        use_cache = self._should_use_cache() and cache_key_prompt
        model_name = self._get_model_name()
        
        if use_cache:
            cached_content = llm_cache.get(cache_key_prompt, model_name)
            if cached_content:
                logger.info(f"[{self.tag}] ✅ 缓存命中，跳过 LLM 调用")
                result = self._create_cached_result(cached_content)
                logger.info(f"[{self.tag}] 执行完成 (from cache)")
                return result
        
        # 调用父类 LLMAgent.run 执行
        result = await super().run(processed_inputs, **kwargs)
        
        # 保存结果到缓存
        if use_cache:
            result_content = self._extract_result_content(result)
            if result_content:
                llm_cache.set(cache_key_prompt, model_name, result_content)
                logger.debug(f"[{self.tag}] 已缓存结果 ({len(result_content)} 字符)")
        
        logger.info(f"[{self.tag}] 执行完成")
        return result
