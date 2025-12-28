"""产物保存回调

职责：
1. 自动识别 Agent 输出类型（文本产物或代码文件）
2. 保存文本产物到 output/artifacts/{session_id}/iteration_{N}/
3. 保存代码文件到 output/repo/

设计原则：
- 文本产物由 ArtifactStore 统一管理（支持 Session/Iteration）
- 代码文件由 FileSystemTool 保存到 output/repo/（跨迭代共享）
- 使用 PathManager 统一管理路径
- 自动识别：如果有代码块，保存代码文件；否则保存文本产物
"""

from typing import List
import os
from pathlib import Path

from ms_agent.agent.runtime import Runtime
from ms_agent.callbacks import Callback
from ms_agent.llm.utils import Message
from ms_agent.tools.filesystem_tool import FileSystemTool
from ms_agent.utils import get_logger
from omegaconf import DictConfig

from src.tools.code.file_parser import extract_code_blocks
from src.utils.artifact_store import ArtifactStore
from src.utils.path_manager import PathManager
from src.utils.workflow_manager import workflow_manager

logger = get_logger()


# Agent 类型分类（用于区分处理逻辑）
TEXT_ONLY_AGENTS = {
    # 只生成文本产物，不生成代码块
    'requirements', 'tech_research', 'architecture', 'risk',
    'evolution', 'planning', 'reflecting', 'summary', 'testing'
}

CODE_GENERATION_AGENTS = {
    # 生成代码块（需要提取并保存）
    'coding'
}

SELF_MANAGED_AGENTS = {
    # 自己管理文件保存，不需要 callback 处理
    'spec_gen'
}


class ArtifactCallback(Callback):
    """产物保存回调
    
    职责：
    1. 自动识别 Agent 输出类型（文本产物或代码文件）
    2. 保存文本产物（research 阶段）到 output/artifacts/{session_id}/iteration_{N}/
    3. 保存代码文件（coding 阶段）到 output/repo/
    
    工作流程：
    1. 在 on_tool_call 中检查是否有代码块
    2. 如果有代码块，保存代码文件
    3. 如果没有代码块，在 on_task_end 中保存文本产物
    """

    def __init__(self, config: DictConfig):
        """初始化回调
        
        步骤：
        1. 初始化 PathManager
        2. 初始化 ArtifactStore（用于保存文本产物）
        3. 初始化 FileSystemTool（用于保存代码文件）
        """
        super().__init__(config)
        
        # 1. 初始化 PathManager
        # 注意：config.output_dir 已经包含 session_id（由 ConfigHandler 设置）
        # 所以不要再传递 session_id 给 PathManager，避免路径重复
        # 例如：config.output_dir = "output/{session_id}/"
        #       如果再传 session_id，会变成 "output/{session_id}/{session_id}/" 错误！
        self.path_manager = PathManager.from_config(config, session_id=None)
        self.path_manager.ensure_dirs()
        
        # 2. 初始化 ArtifactStore（用于保存文本产物）
        self.store = ArtifactStore(
            base_dir=self.path_manager.artifacts_dir,
            session_id=None,  # 路径已经正确，不需要再添加
        )
        
        # 3. 初始化 FileSystemTool（用于保存代码文件）
        # config.output_dir 已经是 session 目录（output/{session_id}/）
        # 直接使用 config.output_dir 即可
        self.file_system = FileSystemTool(config)
        
        logger.info(
            f"[ArtifactCallback] ✅ 初始化完成: "
            f"artifacts_dir={self.path_manager.artifacts_dir}"
        )
        
        # 追踪已保存的产物，避免重复保存
        self._saved_artifacts: set = set()

    async def on_task_begin(self, runtime: Runtime, messages: List[Message]):
        """任务开始时连接文件系统
        
        步骤：
        1. 连接 FileSystemTool
        2. 确保 repo 目录存在
        3. 重置已保存产物追踪（每个任务独立）
        """
        await self.file_system.connect()
        self.path_manager.repo_dir.mkdir(parents=True, exist_ok=True)
        # 重置追踪（每个任务独立追踪）
        self._saved_artifacts = set()

    async def on_generate_response(self, runtime: Runtime, messages: List[Message]):
        """生成响应时处理空内容
        
        处理 LLM 返回空内容但有 tool_calls 的情况
        """
        for message in messages:
            if message.role == 'assistant' and message.tool_calls and not message.content:
                message.content = 'I should do a tool calling to continue:\n'

    async def on_tool_call(self, runtime: Runtime, messages: List[Message]):
        """工具调用时不做处理，延迟到 on_task_end 统一处理
        
        优化原因：
        - 避免重复处理（on_tool_call 和 on_task_end 都会被调用）
        - 工具调用过程中内容可能不完整
        - 统一在任务结束时处理，逻辑更清晰
        """
        pass

    async def on_task_end(self, runtime: Runtime, messages: List[Message]):
        """任务结束时统一处理产物保存
        
        根据 Agent 类型选择处理方式：
        1. SELF_MANAGED_AGENTS（如 spec_gen）：完全跳过
        2. TEXT_ONLY_AGENTS：只保存文本产物
        3. CODE_GENERATION_AGENTS（如 coding）：提取代码块并保存，同时保存文本产物
        """
        agent_tag = self._get_agent_tag(runtime)
        
        # 1. 自管理 Agent：完全跳过
        if agent_tag in SELF_MANAGED_AGENTS:
            logger.debug(f"[ArtifactCallback] [{agent_tag}] 跳过处理（自管理 Agent）")
            return
        
        # 2. 纯文本 Agent：只保存文本产物
        if agent_tag in TEXT_ONLY_AGENTS:
            logger.debug(f"[ArtifactCallback] [{agent_tag}] 保存文本产物")
            await self._save_text_artifact(runtime, messages)
            return
        
        # 3. 代码生成 Agent：提取代码块并保存
        content = self._get_messages_content(messages)
        all_files, _ = extract_code_blocks(content)
        
        logger.info(f"[ArtifactCallback] [{agent_tag}] 提取到 {len(all_files)} 个代码块")
        if all_files:
            for f in all_files[:3]:  # 显示前3个
                logger.info(f"  - {f['filename']} ({len(f.get('code', ''))} 字符)")
        
        # 保存代码文件
        if all_files:
            await self._save_code_files(all_files, messages, runtime=runtime)
        
        # 保存文本产物（编码过程记录）
        await self._save_text_artifact(runtime, messages)

    # --------------------------------------------------------------------- #
    # 私有方法：代码文件保存
    # --------------------------------------------------------------------- #
    
    async def _save_code_files(self, code_files: List[dict], messages: List[Message], runtime: Runtime = None):
        """保存代码文件
        
        步骤：
        1. 规范化文件路径（添加正确的前缀）
        2. 根据文件类型保存到对应位置：
           - repo/ → output/{session_id}/repo/
           - spec_kit/ → output/{session_id}/spec_kit/
           - skills/ → output/skills/（常驻）
        3. 将保存结果添加到消息中
        
        Args:
            code_files: 代码文件列表
            messages: 消息列表
            runtime: Agent 运行时
        """
        if not code_files:
            return
        
        agent_tag = self._get_agent_tag(runtime)
        logger.info(f"[ArtifactCallback] [{agent_tag}] 开始保存 {len(code_files)} 个代码文件")
        
        results = []
        for f in code_files:
            try:
                original_filename = f.get("filename", "unknown")
                file_path = self._normalize_code_file_path(original_filename, agent_tag=agent_tag)
                code = f.get("code", "")
                
                if not code.strip():
                    logger.warning(f"[ArtifactCallback] 跳过空文件: {file_path}")
                    continue
                
                # 根据文件类型选择保存位置
                if file_path.startswith("skills/"):
                    result = await self._save_skill_file(file_path, code)
                else:
                    result = await self._save_session_file(file_path, code)
                
                if result:
                    results.append(result)
                    
            except Exception as e:
                logger.error(f"[ArtifactCallback] 保存文件失败 {f.get('filename', 'unknown')}: {e}")
        
        # 将保存结果添加到消息中
        if results:
            result_text = '\n'.join(results)
            messages.append(Message(role='user', content=result_text))
    
    async def _save_skill_file(self, file_path: str, code: str) -> str:
        """保存 Skill 文件到全局 skills 目录"""
        original_output_dir = self.file_system.output_dir
        try:
            self.file_system.output_dir = str(self.path_manager.skills_dir)
            relative_path = file_path.replace("skills/", "")
            result = await self.file_system.write_file(relative_path, code)
            actual_path = self.path_manager.skills_dir / relative_path
            logger.info(f"[ArtifactCallback] 已保存 Skill: {actual_path}")
            return result
        finally:
            self.file_system.output_dir = original_output_dir
    
    async def _save_session_file(self, file_path: str, code: str) -> str:
        """保存文件到当前 session 目录"""
        result = await self.file_system.write_file(file_path, code)
        
        # 确定实际路径用于日志
        if file_path.startswith("spec_kit/"):
            actual_path = self.path_manager.spec_kit_dir / file_path.replace("spec_kit/", "")
        elif file_path.startswith("repo/"):
            actual_path = self.path_manager.repo_dir / file_path.replace("repo/", "")
        else:
            actual_path = Path(self.file_system.output_dir) / file_path
        
        logger.info(f"[ArtifactCallback] 已保存: {actual_path}")
        return result
    
    def _normalize_code_file_path(self, file_path: str, agent_tag: str = None) -> str:
        """规范化代码文件路径
        
        规则：
        - 已有前缀（repo/、spec_kit/、skills/）：直接返回
        - 根据 agent_tag 判断：
          - spec_gen → spec_kit/
          - summary → skills/
          - 其他 → repo/
        - 后备：根据文件名特征判断
        
        Args:
            file_path: 原始文件路径
            agent_tag: Agent 标签
            
        Returns:
            规范化后的文件路径
        """
        # 已有前缀
        if file_path.startswith(("repo/", "spec_kit/", "skills/")):
            return file_path
        
        # 根据 agent_tag 判断
        if agent_tag:
            if agent_tag == "spec_gen":
                return f"spec_kit/{file_path}"
            elif agent_tag == "summary":
                return f"skills/{file_path}"
            else:
                return f"repo/{file_path}"
        
        # 后备：根据文件名特征判断
        file_basename = Path(file_path).name
        
        # Spec Kit 文件
        if file_basename in ["constitution.md", "spec.md", "plan.md", "tasks.md", "spec_metadata.json"]:
            return f"spec_kit/{file_path}"
        
        # Skill 文件
        if "skill" in file_path.lower():
            return f"skills/{file_path}"
        
        # 默认：repo
        return f"repo/{file_path}"

    # --------------------------------------------------------------------- #
    # 私有方法：文本产物保存
    # --------------------------------------------------------------------- #
    
    async def _save_text_artifact(self, runtime: Runtime, messages: List[Message]):
        """保存文本产物
        
        步骤：
        1. 提取干净的内容（过滤工具调用结果）
        2. 检查是否已保存（避免重复）
        3. 保存到 ArtifactStore
        
        Args:
            runtime: Agent 运行时
            messages: 消息列表
        """
        agent_tag = self._get_agent_tag(runtime)
        
        # 提取内容
        output_content = self._extract_clean_content(messages, runtime)
        if not output_content:
            logger.warning(f"[ArtifactCallback] [{agent_tag}] 未找到可保存的内容")
            return

        # 检查是否已保存
        content_hash = hash(output_content)
        artifact_name = f"{agent_tag}.md"
        artifact_key = f"{artifact_name}:{content_hash}"
        
        if artifact_key in self._saved_artifacts:
            logger.debug(f"[ArtifactCallback] [{agent_tag}] 跳过重复保存")
            return
        
        # 保存
        iteration = workflow_manager.get_iteration()
        if iteration is not None:
            self.store.set_iteration(iteration)

        target_path = self.store.save(artifact_name, output_content, iteration=iteration)
        self._saved_artifacts.add(artifact_key)
        
        logger.info(f"[ArtifactCallback] [{agent_tag}] 已保存文本产物: {target_path} ({len(output_content)} 字符)")

    # --------------------------------------------------------------------- #
    # 私有方法：辅助函数
    # --------------------------------------------------------------------- #
    
    def _get_agent_tag(self, runtime: Runtime) -> str:
        """获取 Agent 标签（统一入口）"""
        return runtime.tag if runtime and hasattr(runtime, 'tag') else 'unknown'
    
    def _get_messages_content(self, messages: List[Message]) -> str:
        """获取所有消息内容（用于代码块提取）"""
        return '\n'.join([m.content for m in messages[2:] if m.content])

    def _extract_clean_content(self, messages: List[Message], runtime: Runtime = None) -> str:
        """提取干净的 Assistant 回复内容（用于文本产物保存）
        
        规则：
        1. 只提取 assistant 消息
        2. 过滤工具调用结果（包含特定关键词）
        3. 返回最后一条有意义的消息
        
        Args:
            messages: 消息列表
            runtime: Agent 运行时
            
        Returns:
            干净的内容
        """
        # 过滤关键词
        filter_keywords = ["save file", "tool call", "file saved successfully", "write_file"]
        
        # 收集所有有效的 assistant 消息
        assistant_messages = []
        for msg in messages:
            if msg.role == "assistant" and msg.content:
                content = msg.content.strip()
                # 过滤工具调用结果
                if any(keyword in content.lower() for keyword in filter_keywords):
                    continue
                assistant_messages.append(content)
        
        if not assistant_messages:
            return ""
        
        # 返回最后一条有意义的消息（如果太短，返回倒数第二条）
        if len(assistant_messages) > 1 and len(assistant_messages[-1]) < 100:
            return assistant_messages[-2]
        
        return assistant_messages[-1]


