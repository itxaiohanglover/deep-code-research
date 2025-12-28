"""DeepCode 工作流

基于 ms-agent 的 ChainWorkflow，增加 Session / 文件输入 / 产物管理。

职责：
1. 管理工作流执行（基于 ChainWorkflow）
2. 处理文档输入（DocumentProcessor）
3. 管理 Session 和 Iteration
4. 规范化 Agent 配置路径（PathResolver）
5. 支持并行执行分析阶段 Agent（提升效率）
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ms_agent.workflow.chain_workflow import ChainWorkflow
from ms_agent.agent.loader import AgentLoader
from ms_agent.config import Config
from ms_agent.utils import get_logger
from omegaconf import DictConfig

from src.tools.document.processor import DocumentProcessor
from src.utils.artifact_store import ArtifactStore
from src.utils.workflow_manager import workflow_manager
from src.utils.path_resolver import PathResolver
from src.utils.change_detector import ChangeDetector, AGENT_DEPENDENCIES
from src.utils.artifact_versioning import ArtifactVersionManager
from src.config.settings import settings

logger = get_logger()


# 可并行执行的 Agent 组配置
# 这些 Agent 的输入只依赖 requirements，不相互依赖，可以并行执行
PARALLEL_AGENT_GROUPS = {
    # 分析阶段并行组：tech_research, architecture, risk 可以并行
    "analysis_parallel": ["tech_research", "architecture", "risk"],
}

# 并行组的前置依赖
PARALLEL_GROUP_DEPENDENCIES = {
    "analysis_parallel": "requirements",  # 需要 requirements 完成后才能开始
}


class DeepCodeResearchWorkflow(ChainWorkflow):
    """DeepCode 工作流（基于 ChainWorkflow）
    
    职责：
    1. 管理工作流执行（基于 ChainWorkflow）
    2. 处理文档输入（DocumentProcessor）
    3. 管理 Session 和 Iteration
    4. 规范化 Agent 配置路径（PathResolver）
    5. 支持增量执行（跳过无变更的 Agent）
    6. 支持产物版本管理
    """

    WORKFLOW_NAME = "DeepCodeResearchWorkflow"
    
    # 增量执行相关属性
    _change_detector: Optional[ChangeDetector] = None
    _version_manager: Optional[ArtifactVersionManager] = None

    def build_workflow(self):
        """构建工作流
        
        步骤：
        1. 调用父类方法构建工作流
        2. 初始化项目根目录和输出目录
        3. 初始化上传目录
        4. 根据工作流模式过滤 Agent 列表
        """
        super().build_workflow()
        
        # 计算项目根目录：从 src/config 向上两级到项目根目录
        config_dir = Path(self.config.local_dir).resolve()
        self.project_root = config_dir.parent.parent.resolve()
        
        # 使用环境变量 OUTPUT_DIR，如果没有则使用项目根目录下的 output
        output_dir_env = os.getenv("OUTPUT_DIR")
        if output_dir_env:
            self.output_root = Path(output_dir_env).resolve()
        else:
            self.output_root = self.project_root / "output"
        
        logger.info(f"[DeepCodeWorkflow] 项目根目录: {self.project_root}")
        logger.info(f"[DeepCodeWorkflow] 输出目录: {self.output_root}")
        
        # 根据工作流模式过滤 Agent 列表
        self._apply_workflow_mode()
    
    def _apply_workflow_mode(self) -> None:
        """根据工作流模式过滤 Agent 列表
        
        通过环境变量 WORKFLOW_MODE 控制：
        - full: 完整模式，执行所有 Agent（默认）
        - fast: 快速模式，只执行核心 Agent（预计提速 20-50%）
        - minimal: 最小模式，只执行最核心的 Agent
        """
        # 获取工作流模式配置
        workflow_config = settings.workflow
        mode = workflow_config.mode
        
        if mode == "full":
            logger.info(f"[DeepCodeWorkflow] 🔄 使用完整模式，执行所有 {len(self.workflow_chains)} 个 Agent")
            return
        
        # 获取当前模式需要执行的 Agent 列表
        active_agents = workflow_config.get_active_agents()
        
        # 过滤 workflow_chains，只保留该模式需要的 Agent
        original_chains = self.workflow_chains.copy()
        self.workflow_chains = [
            agent for agent in self.workflow_chains
            if agent in active_agents
        ]
        
        skipped_agents = [a for a in original_chains if a not in self.workflow_chains]
        
        logger.info(
            f"[DeepCodeWorkflow] ⚡ 使用 {mode} 模式\n"
            f"  执行 {len(self.workflow_chains)} 个 Agent: {self.workflow_chains}\n"
            f"  跳过 {len(skipped_agents)} 个 Agent: {skipped_agents}"
        )

    async def run(self, inputs, **kwargs):
        """执行工作流，支持 query + files 的输入
        
        步骤：
        1. 规范化输入（query + files）
        2. 准备环境（设置环境变量，包括修复 llm_base_url）
        3. 处理文档（如果有）
        4. 构建初始输入
        5. 执行工作流（带路径规范化）
        """
        # 1. 规范化输入
        request = self._normalize_inputs(inputs)
        self.session_id = request["session_id"]
        
        # 2. 准备环境（必须在任何配置加载之前执行）
        self._prepare_env()
        
        # 3. 处理文档（如果有）
        document_summary = self._process_documents(request["files"])
        
        # 4. 构建初始输入
        initial_input = self._build_initial_input(request["query"], document_summary)
        
        # 5. 设置迭代
        workflow_manager.set_iteration(1)
        
        # 6. 重置共享 RAG 服务（每次 workflow 开始时）
        self._reset_rag_service()
        
        logger.info(f"[DeepCodeWorkflow] 开始执行工作流 (session={self.session_id})")
        
        # 7. 初始化增量执行组件
        self._init_incremental_execution()
        
        # 8. 记录初始输入变更
        if self._change_detector:
            self._change_detector.update_input_hash("user_input", initial_input)
        
        # 9. 执行工作流（带路径规范化和增量执行）
        result = await self._run_with_path_normalization(initial_input, **kwargs)
        
        logger.info(f"[DeepCodeWorkflow] 工作流执行完成 (session={self.session_id})")
        return result
    
    def _init_incremental_execution(self) -> None:
        """初始化增量执行组件
        
        包括：
        1. ChangeDetector - 变更检测
        2. ArtifactVersionManager - 版本管理
        """
        # 检查是否启用增量执行
        enable_incremental = os.getenv("INCREMENTAL_EXECUTION", "true").lower() == "true"
        if not enable_incremental:
            logger.info("[DeepCodeWorkflow] 增量执行已禁用")
            return
        
        try:
            from src.utils.path_manager import PathManager
            path_manager = PathManager.from_env(session_id=self.session_id)
            session_dir = path_manager.output_dir / self.session_id
            
            self._change_detector = ChangeDetector(session_dir)
            self._version_manager = ArtifactVersionManager(session_dir)
            
            logger.info("[DeepCodeWorkflow] ✅ 增量执行已启用")
            summary = self._change_detector.get_summary()
            if summary["total_agents"] > 0:
                logger.info(f"[DeepCodeWorkflow] 检测到历史执行记录: {summary['total_agents']} 个 Agent")
        except Exception as e:
            logger.warning(f"[DeepCodeWorkflow] 初始化增量执行失败: {e}")
            self._change_detector = None
            self._version_manager = None
    
    def _should_skip_agent(self, task: str, input_content: str) -> Tuple[bool, str]:
        """检查是否可以跳过 Agent 执行
        
        Args:
            task: 任务名称
            input_content: 输入内容
            
        Returns:
            (是否跳过, 原因)
        """
        if not self._change_detector:
            return False, "增量执行未启用"
        
        # 检查是否强制执行
        force_agents = os.getenv("FORCE_AGENTS", "").split(",")
        if task in force_agents or "*" in force_agents:
            return False, "强制执行"
        
        # 使用 ChangeDetector 判断
        should_exec, reason = self._change_detector.should_execute(task, input_content)
        
        if not should_exec:
            return True, reason
        
        return False, reason

    def _is_parallel_enabled(self) -> bool:
        """检查是否启用并行执行
        
        可通过环境变量 PARALLEL_ANALYSIS=false 禁用
        
        Returns:
            是否启用并行执行
        """
        env_value = os.getenv("PARALLEL_ANALYSIS", "true").lower()
        return env_value not in ("false", "0", "no")
    
    def _get_parallel_group(self, task: str) -> Tuple[str, List[str]] | None:
        """获取任务所属的并行组
        
        Args:
            task: 任务名称
            
        Returns:
            (组名, 组内任务列表) 或 None（如果不属于任何并行组）
        """
        for group_name, tasks in PARALLEL_AGENT_GROUPS.items():
            if task in tasks:
                return group_name, tasks
        return None
    
    async def _run_parallel_agents(
        self,
        tasks: List[str],
        inputs: Any,
        path_resolver: PathResolver,
        **kwargs
    ) -> Dict[str, Any]:
        """并行执行多个 Agent（使用线程池实现真正并行）
        
        Args:
            tasks: 要并行执行的任务列表
            inputs: 输入数据
            path_resolver: 路径解析器
            **kwargs: 其他参数
            
        Returns:
            任务名到输出的映射字典
            
        实现说明：
            由于 LLM 调用可能是同步阻塞的（使用 requests 而非 aiohttp），
            单纯使用 asyncio.gather 无法实现真正并行。
            
            解决方案：使用 asyncio.to_thread() 将每个 Agent 的执行
            放到线程池中，实现真正的 CPU 级并行。
        """
        import concurrent.futures
        
        logger.info(f"[DeepCodeWorkflow] 🚀 开始并行执行 {len(tasks)} 个 Agent: {tasks}")
        
        # 步骤 1：同步初始化所有 Agent
        engines = {}
        configs_map = {}
        for task in tasks:
            task_info = getattr(self.config, task)
            config = getattr(task_info, 'agent_config', None)
            
            # 加载并规范化配置
            if isinstance(config, str):
                config = self._load_and_normalize_config(config, task, path_resolver)
            
            # 构建 Agent 初始化参数
            init_args = self._build_agent_init_args(task_info, task, config)
            
            # 构建 Agent（同步）
            engine = AgentLoader.build(**init_args)
            engines[task] = engine
            configs_map[task] = engine.config
            logger.info(f"[DeepCodeWorkflow] 📦 {task} Agent 初始化完成")
        
        # 步骤 2：使用线程池实现真正并行
        def run_agent_sync(task: str) -> Tuple[str, Any]:
            """在线程中同步运行 Agent"""
            logger.info(f"[DeepCodeWorkflow] ⏳ 开始执行 {task}")
            # 在新线程中创建事件循环运行异步代码
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                outputs = loop.run_until_complete(engines[task].run(inputs))
                logger.info(f"[DeepCodeWorkflow] ✅ {task} 执行完成")
                return task, outputs
            finally:
                loop.close()
        
        logger.info(f"[DeepCodeWorkflow] 🔥 所有 Agent 初始化完成，开始真正并行执行（线程池模式）...")
        
        # 使用线程池并行执行
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = [
                loop.run_in_executor(executor, run_agent_sync, task)
                for task in tasks
            ]
            results = await asyncio.gather(*futures, return_exceptions=True)
        
        # 处理结果
        outputs_map = {}
        
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"[DeepCodeWorkflow] ❌ 并行执行异常: {result}")
                raise result
            
            task, outputs = result
            outputs_map[task] = outputs
        
        logger.info(f"[DeepCodeWorkflow] 🎉 并行执行完成: {list(outputs_map.keys())}")
        
        return outputs_map, configs_map

    async def _run_with_path_normalization(self, inputs, **kwargs):
        """执行工作流，在构建 Agent 之前规范化路径
        
        步骤：
        1. 初始化 PathResolver
        2. 遍历工作流链，对每个 Agent 配置进行路径规范化
        3. 检测并行执行机会，并行执行独立的 Agent
        4. 支持流程跳转（前进和回退）
        5. 管理迭代次数（回退时增加迭代）
        
        并行执行策略：
        - 检测到属于并行组的任务时，一次性并行执行整个组
        - 并行组执行完后，跳过组内的后续任务，直接进入下一阶段
        
        注意：
        - 保存初始输入，回退到 requirements 时使用初始输入
        - 回退时增加迭代次数，避免覆盖之前的产物
        """
        agent_config = None
        idx = 0
        step_inputs = {}
        
        # 保存初始输入（用于回退到 requirements 时）
        initial_inputs = inputs
        
        # 初始化 PathResolver
        path_resolver = PathResolver(self.project_root, Path(self.config.local_dir))
        
        # 记录已并行执行的组
        executed_parallel_groups: Set[str] = set()
        
        # 检查是否启用并行执行
        parallel_enabled = self._is_parallel_enabled()
        if parallel_enabled:
            logger.info("[DeepCodeWorkflow] ⚡ 并行执行模式已启用")
        
        while True:
            task = self.workflow_chains[idx]
            
            # 检查是否属于并行组
            parallel_info = self._get_parallel_group(task)
            
            if parallel_enabled and parallel_info and parallel_info[0] not in executed_parallel_groups:
                group_name, group_tasks = parallel_info
                
                # 验证并行组的所有任务都在工作流中
                valid_tasks = [t for t in group_tasks if t in self.workflow_chains]
                
                if len(valid_tasks) > 1:
                    # 并行执行整个组
                    logger.info(f"[DeepCodeWorkflow] 🔄 检测到并行组 '{group_name}': {valid_tasks}")
                    
                    outputs_map, configs_map = await self._run_parallel_agents(
                        valid_tasks, inputs, path_resolver, **kwargs
                    )
                    
                    # 记录已执行的组
                    executed_parallel_groups.add(group_name)
                    
                    # 保存每个任务的输入（用于回退）
                    for t in valid_tasks:
                        t_idx = self.workflow_chains.index(t)
                        step_inputs[t_idx] = (inputs, configs_map.get(t))
                    
                    # 使用最后一个任务的输出作为下一阶段的输入
                    last_task = valid_tasks[-1]
                    outputs = outputs_map[last_task]
                    agent_config = configs_map[last_task]
                    
                    # 跳转到并行组最后一个任务的下一个
                    last_task_idx = max(self.workflow_chains.index(t) for t in valid_tasks)
                    idx = last_task_idx + 1
                    inputs = outputs
                    
                    if idx >= len(self.workflow_chains):
                        break
                    continue
            
            # 串行执行单个 Agent
            task_info = getattr(self.config, task)
            config = getattr(task_info, 'agent_config', agent_config)
            
            # 加载并规范化配置
            if isinstance(config, str):
                config = self._load_and_normalize_config(config, task, path_resolver)
            
            # 检查是否可以跳过执行（增量执行）
            input_str = inputs if isinstance(inputs, str) else str(inputs)
            skip_execution, skip_reason = self._should_skip_agent(task, input_str)
            
            if skip_execution:
                logger.info(f"[DeepCodeWorkflow] ⏭️ 跳过 {task}: {skip_reason}")
                # 从缓存加载之前的输出
                cached_output = self._load_cached_output(task)
                if cached_output:
                    outputs = cached_output
                    step_inputs[idx] = (inputs, config)
                    idx += 1
                    inputs = outputs
                    if idx >= len(self.workflow_chains):
                        break
                    continue
                else:
                    logger.warning(f"[DeepCodeWorkflow] 未找到缓存输出，执行 {task}")
            
            # 构建 Agent 初始化参数
            init_args = self._build_agent_init_args(task_info, task, config)
            
            # 构建并运行 Agent
            engine = AgentLoader.build(**init_args)
            step_inputs[idx] = (inputs, config)
            outputs = await engine.run(inputs)
            
            # 记录执行信息（用于增量执行）
            self._record_execution(task, input_str, outputs)
            
            # 处理下一步
            next_idx = engine.next_flow(idx)
            
            # 检查是否回退（next_idx < idx）
            if next_idx < idx:
                # 回退时增加迭代次数，避免覆盖之前的产物
                current_iteration = workflow_manager.get_iteration()
                workflow_manager.set_iteration(current_iteration + 1)
                logger.info(
                    f"[DeepCodeWorkflow] 流程回退: {task}({idx}) -> {self.workflow_chains[next_idx]}({next_idx}), "
                    f"迭代次数: {current_iteration} -> {current_iteration + 1}"
                )
                
                # 回退时清除已执行的并行组记录（允许重新并行执行）
                executed_parallel_groups.clear()
                
                # 回退到 requirements 时，使用初始输入
                if next_idx == 0:  # requirements 是第一个
                    inputs = initial_inputs
                    logger.debug(f"[DeepCodeWorkflow] 回退到 requirements，使用初始输入")
                else:
                    # 其他回退情况，使用对应步骤的输入
                    if next_idx in step_inputs:
                        inputs, agent_config = step_inputs[next_idx]
                    else:
                        # 如果对应步骤的输入不存在，使用当前输出
                        inputs = outputs
            elif next_idx == idx + 1:
                # 正常前进
                inputs = outputs
                agent_config = engine.config
            else:
                # 不允许跳过步骤（next_idx > idx + 1）
                logger.warning(
                    f"[DeepCodeWorkflow] 不允许跳过步骤: {task}({idx}) -> {self.workflow_chains[next_idx]}({next_idx})"
                )
                next_idx = idx + 1
                inputs = outputs
                agent_config = engine.config
            
            idx = next_idx
            if idx >= len(self.workflow_chains):
                break
        
        return inputs

    # ------------------------------------------------------------------ #
    # 私有方法：配置加载和规范化
    # ------------------------------------------------------------------ #
    
    def _load_and_normalize_config(self, config_path_str: str, task: str, path_resolver: PathResolver) -> DictConfig:
        """加载并规范化 Agent 配置（自动合并 _base.yaml）
        
        步骤：
        1. 修复环境变量映射（llm_base_url KeyError）
        2. 解析配置路径
        3. 加载基础配置（_base.yaml）
        4. 加载 Agent 特定配置
        5. 合并配置（Agent 配置覆盖基础配置）
        6. 规范化路径
        7. 返回配置对象
        
        Args:
            config_path_str: 配置路径字符串（相对于 local_dir）
            task: 任务名称
            path_resolver: 路径解析器
            
        Returns:
            规范化后的配置对象
        """
        from omegaconf import OmegaConf
        
        # Fix: Ensure llm_base_url is available before Config.from_task() calls
        # This must be done here as well, in case _prepare_env() wasn't called yet
        self._fix_llm_env_vars()
        
        config_path = Path(self.config.local_dir) / config_path_str
        
        # 1. 加载基础配置（_base.yaml）
        base_config_path = Path(self.config.local_dir) / "agents" / "_base.yaml"
        base_config = None
        if base_config_path.exists():
            _argv = sys.argv[:]
            try:
                sys.argv = [sys.argv[0]]
                # 使用 OmegaConf.load() 加载，会自动解析 ${oc.env:...} 变量
                # 环境变量应该已经在 self.env 中设置
                base_config = OmegaConf.load(str(base_config_path))
                # 确保 local_dir 和 name 属性存在（与 Config.from_task 保持一致）
                if not hasattr(base_config, 'local_dir'):
                    base_config.local_dir = str(base_config_path.parent.parent)
                if not hasattr(base_config, 'name'):
                    base_config.name = "_base.yaml"
            finally:
                sys.argv = _argv
            logger.debug(f"[DeepCodeWorkflow] 已加载基础配置: {base_config_path}")
        else:
            logger.warning(f"[DeepCodeWorkflow] 未找到基础配置文件: {base_config_path}")
        
        # 2. 加载 Agent 特定配置
        _argv = sys.argv[:]
        try:
            sys.argv = [sys.argv[0]]
            agent_config_obj = Config.from_task(str(config_path), self.env)
        finally:
            sys.argv = _argv
        
        # 3. 合并配置（Agent 配置覆盖基础配置）
        if base_config is not None:
            # DEBUG: 检查 base_config 中的 callbacks
            base_callbacks = getattr(base_config, 'callbacks', None)
            logger.debug(f"[DeepCodeWorkflow] [{task}] base_config.callbacks = {list(base_callbacks) if base_callbacks else None}")
            
            merged_config = OmegaConf.merge(base_config, agent_config_obj)
            logger.debug(f"[DeepCodeWorkflow] 已合并基础配置和 Agent 配置: {config_path}")
        else:
            merged_config = agent_config_obj
            logger.debug(f"[DeepCodeWorkflow] 未合并基础配置（使用 Agent 配置）: {config_path}")
        
        # 4. 规范化路径
        path_resolver.config_dir = config_path.parent
        path_resolver.normalize_all_paths(merged_config, task)
        
        # DEBUG: 打印 callbacks 配置
        callbacks = getattr(merged_config, 'callbacks', None)
        if callbacks:
            logger.debug(f"[DeepCodeWorkflow] [{task}] callbacks 配置: {list(callbacks)}")
        else:
            logger.warning(f"[DeepCodeWorkflow] [{task}] ⚠️ 未找到 callbacks 配置")
        
        return merged_config
    
    def _build_agent_init_args(self, task_info: DictConfig, task: str, config: DictConfig | str) -> Dict:
        """构建 Agent 初始化参数
        
        Args:
            task_info: 任务信息配置
            task: 任务名称
            config: Agent 配置（DictConfig 或路径字符串）
            
        Returns:
            Agent 初始化参数字典
        """
        if not hasattr(task_info, 'agent'):
            task_info.agent = DictConfig({})
        
        init_args = getattr(task_info.agent, 'kwargs', {}).copy()
        init_args.pop('trust_remote_code', None)
        init_args['trust_remote_code'] = self.trust_remote_code
        init_args['mcp_server_file'] = self.mcp_server_file
        init_args['task'] = task
        init_args['load_cache'] = self.load_cache
        
        if isinstance(config, str):
            init_args['config_dir_or_id'] = os.path.join(self.config.local_dir, config)
        else:
            init_args['config'] = config
        
        init_args['env'] = self.env
        
        if 'tag' not in init_args:
            init_args['tag'] = task
        
        return init_args

    # ------------------------------------------------------------------ #
    # 私有方法：输入处理
    # ------------------------------------------------------------------ #
    
    def _normalize_inputs(self, inputs: Any) -> Dict[str, Any]:
        """规范化输入
        
        支持两种输入格式：
        1. 字符串：query
        2. 字典：{"query": "...", "files": [...], "session_id": "..."}
        
        Args:
            inputs: 输入（字符串或字典）
            
        Returns:
            规范化后的输入字典
        """
        if isinstance(inputs, dict):
            query = inputs.get("query", "")
            files = inputs.get("files") or []
            session_id = inputs.get("session_id") or self._generate_session_id()
        elif isinstance(inputs, str):
            query = inputs
            files = []
            session_id = self._generate_session_id()
        else:
            raise ValueError("DeepCodeWorkflow inputs must be str or dict")

        file_paths = [str(Path(f)) for f in files if f]
        return {
            "query": query.strip(),
            "files": file_paths,
            "session_id": session_id,
        }

    def _process_documents(self, files: list[str]) -> Dict[str, Any] | None:
        """处理文档
        
        步骤：
        1. 如果没有文件，返回 None
        2. 初始化 DocumentProcessor 和 ArtifactStore
        3. 处理文档并保存摘要
        
        Args:
            files: 文件路径列表
            
        Returns:
            文档摘要字典或 None
        """
        if not files:
            return None
        
        # 初始化组件（懒加载）
        # 使用 PathManager 获取正确的路径（按会话分类）
        from src.utils.path_manager import PathManager
        path_manager = PathManager.from_env(session_id=self.session_id)
        path_manager.ensure_dirs()
        
        # 初始化文档处理器，启用图片分析
        # 图片保存到 {session_dir}/images/ 目录
        images_dir = path_manager.output_dir / self.session_id / "images"
        document_processor = DocumentProcessor(
            config=getattr(self, 'config', None),
            upload_root=path_manager.uploads_dir,
            enable_vision=True,  # 启用 VLM 视觉分析
            enable_ocr=True,     # 启用 OCR 文字提取
            images_dir=images_dir,
        )
        # 注意：path_manager.artifacts_dir 已经是 output/{session_id}/artifacts/
        # 所以不需要再传入 session_id，避免重复添加 session_id 子目录
        artifact_store = ArtifactStore(
            base_dir=path_manager.artifacts_dir,
            session_id=None,  # base_dir 已经包含 session_id，不需要再添加
        )
        
        # 处理文档
        document_summary = document_processor.process(
            files, session_id=self.session_id
        )
        
        # 保存文档摘要
        artifact_store.set_iteration(0)
        artifact_store.save_json(
            "documents/uploads_summary.json",
            document_summary,
            iteration=0,
        )
        
        return document_summary

    def _build_initial_input(self, query: str, document_summary: Dict[str, Any] | None) -> str:
        """构建初始输入
        
        步骤：
        1. 如果没有任何文档，直接返回 query
        2. 如果有文档，构建包含文档上下文的输入
        
        Args:
            query: 用户查询
            document_summary: 文档摘要
            
        Returns:
            构建后的初始输入
        """
        query = query.strip()
        if not document_summary or not document_summary.get("files"):
            return query

        # 临时创建 DocumentProcessor 用于格式化摘要（不需要启用图片分析）
        from src.utils.path_manager import PathManager
        path_manager = PathManager.from_env(session_id=self.session_id)
        document_processor = DocumentProcessor(
            upload_root=path_manager.uploads_dir,
            enable_vision=False,  # 格式化摘要不需要视觉分析
            enable_ocr=False,     # 格式化摘要不需要 OCR
        )
        document_context = document_processor.format_summary(document_summary)
        
        return (
            f"{query}\n\n"
            "## Uploaded Documents Context\n"
            f"{document_context}"
        )

    # ------------------------------------------------------------------ #
    # 私有方法：环境准备
    # ------------------------------------------------------------------ #
    
    def _prepare_env(self) -> None:
        """设置工作流运行所需的环境变量
        
        步骤：
        1. 初始化 env 字典（如果不存在）
        2. 修复 llm_base_url 环境变量映射（必须在配置加载前）
        3. 设置 OUTPUT_DIR 和 output_dir
        4. 设置 SESSION_ID
        5. 同步到 os.environ
        """
        output_dir = str(self.output_root)
        self.env = self.env or os.environ.copy()
        
        # Fix: Ensure llm_base_url is available from MODELSCOPE_BASE_URL
        # This must be done before any Config.from_task() calls
        self._fix_llm_env_vars()
        
        # 设置环境变量（同时设置大小写版本，兼容不同使用方式）
        self.env["OUTPUT_DIR"] = output_dir
        self.env["output_dir"] = output_dir
        self.env["SESSION_ID"] = self.session_id
        
        # 同步到 os.environ（供其他模块使用）
        os.environ["OUTPUT_DIR"] = output_dir
        os.environ["SESSION_ID"] = self.session_id
    
    def _fix_llm_env_vars(self) -> None:
        """修复 llm_base_url 环境变量映射
        
        解决 ms-agent Config.from_task() 中的 KeyError: 'llm_base_url'
        ms-agent 的 _update_config() 会查找 <llm_base_url> 占位符
        
        注意：必须同时设置小写键名（llm_base_url）和大写键名（LLM_BASE_URL），
        因为配置文件中可能使用 <llm_base_url> 或 <LLM_BASE_URL>
        """
        # Get MODELSCOPE_BASE_URL from environment or self.env
        modelscope_base_url = os.getenv('MODELSCOPE_BASE_URL') or (self.env.get('MODELSCOPE_BASE_URL') if hasattr(self, 'env') and self.env else None)
        if modelscope_base_url:
            # Set both lowercase and uppercase keys in os.environ and self.env
            # ms-agent's _update_config() checks for exact key match: value[1:-1] in extra
            # So we need both 'llm_base_url' and 'LLM_BASE_URL'
            os.environ['LLM_BASE_URL'] = modelscope_base_url
            os.environ['llm_base_url'] = modelscope_base_url  # 小写键名
            if not hasattr(self, 'env') or not self.env:
                self.env = os.environ.copy()
            self.env['LLM_BASE_URL'] = modelscope_base_url
            self.env['llm_base_url'] = modelscope_base_url  # 小写键名
            logger.debug(f'[DeepCodeWorkflow] 设置 LLM_BASE_URL = {modelscope_base_url} (大小写)')
        
        # Get MODELSCOPE_API_KEY from environment or self.env
        modelscope_api_key = os.getenv('MODELSCOPE_API_KEY') or (self.env.get('MODELSCOPE_API_KEY') if hasattr(self, 'env') and self.env else None)
        if modelscope_api_key:
            # Set both lowercase and uppercase keys in os.environ and self.env
            os.environ['LLM_API_KEY'] = modelscope_api_key
            os.environ['llm_api_key'] = modelscope_api_key  # 小写键名
            if not hasattr(self, 'env') or not self.env:
                self.env = os.environ.copy()
            self.env['LLM_API_KEY'] = modelscope_api_key
            self.env['llm_api_key'] = modelscope_api_key  # 小写键名
            logger.debug('[DeepCodeWorkflow] 设置 LLM_API_KEY (大小写)')

    @staticmethod
    def _generate_session_id() -> str:
        """生成 Session ID
        
        Returns:
            12 位十六进制字符串
        """
        return uuid.uuid4().hex[:12]

    def _reset_rag_service(self) -> None:
        """重置共享 RAG 服务
        
        每次 workflow 开始时重置 RAG 服务，确保新的会话不会使用旧的知识库索引。
        """
        try:
            from src.tools.rag import shared_rag_service
            shared_rag_service.reset()
            logger.debug("[DeepCodeWorkflow] 共享 RAG 服务已重置")
        except ImportError:
            pass
    
    # ------------------------------------------------------------------ #
    # 增量执行相关方法
    # ------------------------------------------------------------------ #
    
    def _record_execution(self, task: str, input_content: str, outputs: Any) -> None:
        """记录 Agent 执行信息
        
        Args:
            task: 任务名称
            input_content: 输入内容
            outputs: 输出内容
        """
        if not self._change_detector:
            return
        
        try:
            # 计算 hash
            input_hash = self._change_detector.compute_hash(input_content)
            output_str = outputs if isinstance(outputs, str) else str(outputs)
            output_hash = self._change_detector.compute_hash(output_str)
            
            # 获取依赖
            dependencies = AGENT_DEPENDENCIES.get(task, [])
            
            # 记录执行
            self._change_detector.mark_executed(
                agent_name=task,
                input_hash=input_hash,
                output_hash=output_hash,
                dependencies=dependencies,
                metadata={"iteration": workflow_manager.get_iteration()},
            )
            
            # 保存版本
            if self._version_manager:
                self._version_manager.save_version(
                    artifact_name=task,
                    content=output_str,
                    metadata={"iteration": workflow_manager.get_iteration()},
                )
                
        except Exception as e:
            logger.warning(f"[DeepCodeWorkflow] 记录执行信息失败: {e}")
    
    def _load_cached_output(self, task: str) -> Optional[str]:
        """加载缓存的输出
        
        Args:
            task: 任务名称
            
        Returns:
            缓存的输出或 None
        """
        if not self._version_manager:
            return None
        
        try:
            version = self._version_manager.get_latest_version(task)
            if version:
                logger.debug(f"[DeepCodeWorkflow] 加载缓存输出: {task}/{version.version_id}")
                return version.content
        except Exception as e:
            logger.warning(f"[DeepCodeWorkflow] 加载缓存输出失败: {e}")
        
        return None
    
    def get_execution_summary(self) -> Dict[str, Any]:
        """获取执行摘要
        
        Returns:
            执行摘要信息
        """
        summary = {
            "session_id": getattr(self, "session_id", None),
            "incremental_enabled": self._change_detector is not None,
        }
        
        if self._change_detector:
            summary["change_detection"] = self._change_detector.get_summary()
        
        if self._version_manager:
            summary["version_management"] = self._version_manager.get_summary()
        
        return summary
