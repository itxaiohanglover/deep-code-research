"""SpecKit 生成 Agent - Phase 5

职责：
1. 基于所有前序研究结果，并行生成 4 个 Spec Kit 文档  
2. 使用规则提取生成 spec_metadata.json（快速且可靠）
3. 直接保存所有文件到 spec_kit 目录

设计原则：
- LLM 生成结构化文档（Markdown）
- 规则提取生成元数据（JSON）
- 使用线程池实现真正并行（绕过 asyncio 的假并行问题）
"""

import asyncio
import concurrent.futures
import os
from pathlib import Path
from typing import Any, List, Dict, Optional, Tuple
from ms_agent.llm.utils import Message

from ms_agent.utils import get_logger

from src.agents._base_agent import BaseAgent
from src.prompts.spec_gen_prompts import (
    build_constitution_prompt,
    build_spec_prompt,
    build_plan_prompt,
    build_tasks_prompt
)
from src.utils.path_manager import PathManager

logger = get_logger()


# 文档配置：名称和对应的 prompt 构建函数
SPEC_KIT_DOCS = [
    ("constitution.md", build_constitution_prompt),
    ("spec.md", build_spec_prompt),
    ("plan.md", build_plan_prompt),
    ("tasks.md", build_tasks_prompt),
]


class SpecGenAgent(BaseAgent):
    """SpecKit 生成 Agent
    
    职责：
    1. 并行生成 4 个 Spec Kit Markdown 文档
    2. 使用 LLM 生成 spec_metadata.json（智能、可靠）
    """
    
    def _get_concurrency(self) -> int:
        """获取并发限制
        
        从环境变量或配置中读取，默认为 2。
        """
        return int(os.getenv("SPEC_GEN_CONCURRENCY", "2"))
    
    def _get_path_manager(self) -> PathManager:
        """获取 PathManager 实例
        
        注意：config.output_dir 已经包含 session_id（由 ConfigHandler 设置）
        """
        return PathManager.from_config(self.config, session_id=None)
    
    def _save_spec_file(self, filename: str, content: str) -> None:
        """保存 Spec Kit 文件
        
        Args:
            filename: 文件名（如 constitution.md）
            content: 文件内容
        """
        spec_kit_dir = self._get_path_manager().spec_kit_dir
        spec_kit_dir.mkdir(parents=True, exist_ok=True)
        
        file_path = spec_kit_dir / filename
        file_path.write_text(content, encoding='utf-8')
        logger.info(f"[{self.tag}] ✅ 已保存 {filename} ({len(content)} 字符) -> {file_path}")
    
    def _build_prompt(self, user_input: str) -> str:
        """构建 SpecKit 生成提示词
        
        此方法保留以兼容 BaseAgent 接口，实际生成由 run() 处理。
        """
        return user_input
    
    def _get_previous_artifacts(self) -> Dict[str, str]:
        """获取所有前序研究产物"""
        return {
            "requirements": self._get_previous_artifact("requirements", default=""),
            "tech_research": self._get_previous_artifact("tech_research", default=""),
            "architecture": self._get_previous_artifact("architecture", default=""),
            "risk": self._get_previous_artifact("risk", default=""),
        }
    
    async def _generate_single_document(
        self,
        doc_name: str,
        prompt_builder,
        user_input: str,
        artifacts: Dict[str, str],
        **kwargs
    ) -> Dict[str, Any]:
        """生成单个文档"""
        prompt = prompt_builder(
            user_input=user_input,
            requirements=artifacts.get("requirements") or None,
            tech_research=artifacts.get("tech_research") or None,
            architecture=artifacts.get("architecture") or None,
            risk=artifacts.get("risk") or None
        )
        
        # 临时替换 _build_prompt
        original_build_prompt = self._build_prompt
        self._build_prompt = lambda _: prompt
        
        try:
            logger.info(f"[{self.tag}] 开始生成 {doc_name}")
            result = await super().run(user_input, **kwargs)
            content = self._extract_content(result)
            self._save_spec_file(doc_name, content)
            logger.info(f"[{self.tag}] {doc_name} 生成完成 ({len(content)} 字符)")
            return {"name": doc_name, "content": content, "success": True}
        except Exception as e:
            logger.error(f"[{self.tag}] 生成 {doc_name} 失败: {e}")
            return {"name": doc_name, "content": "", "success": False, "error": str(e)}
        finally:
            self._build_prompt = original_build_prompt
    
    def _extract_content(self, result: Any) -> str:
        """从 LLM 结果中提取内容"""
        if isinstance(result, list):
            for msg in reversed(result):
                if isinstance(msg, Message) and msg.role == "assistant" and msg.content:
                    return msg.content
            return ""
        elif isinstance(result, str):
            return result
        return str(result) if result else ""
    
    async def run(self, inputs: Any, **kwargs: Any) -> Any:
        """运行 Agent，生成完整的 Spec Kit（使用线程池真正并行）
        
        步骤：
        1. 使用线程池并行生成 4 个 Markdown 文档
        2. 使用规则提取生成 spec_metadata.json
        
        实现说明：
        由于 LLM 调用是同步阻塞的，asyncio.gather 无法实现真正并行。
        改用 ThreadPoolExecutor 实现 CPU 级并行。
        """
        concurrency = self._get_concurrency()
        logger.info(f"[{self.tag}] 开始执行（线程池并行生成 {len(SPEC_KIT_DOCS)} 个文档，并发: {concurrency}）")
        
        artifacts = self._get_previous_artifacts()
        user_input = inputs if isinstance(inputs, str) else str(inputs)
        
        # 使用线程池实现真正并行
        def generate_doc_sync(doc_info: Tuple[str, callable]) -> Dict[str, Any]:
            """在线程中同步生成单个文档"""
            doc_name, prompt_builder = doc_info
            logger.info(f"[{self.tag}] ⏳ 开始生成 {doc_name}")
            
            # 在新线程中创建事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(
                    self._generate_single_document(
                        doc_name, prompt_builder, user_input, artifacts, **kwargs
                    )
                )
                logger.info(f"[{self.tag}] ✅ {doc_name} 生成完成")
                return result
            except Exception as e:
                logger.error(f"[{self.tag}] ❌ {doc_name} 生成失败: {e}")
                return {"name": doc_name, "content": "", "success": False, "error": str(e)}
            finally:
                loop.close()
        
        logger.info(f"[{self.tag}] 🔥 开始真正并行生成 4 个文档...")
        
        # 使用线程池并行执行
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                loop.run_in_executor(executor, generate_doc_sync, doc_info)
                for doc_info in SPEC_KIT_DOCS
            ]
            results = await asyncio.gather(*futures, return_exceptions=True)
        
        # 处理结果
        generated_docs = []
        doc_contents = {}
        
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"[{self.tag}] 文档生成异常: {result}")
                continue
            if result.get("success"):
                doc_name = result["name"]
                content = result["content"]
                generated_docs.append(doc_name)
                doc_contents[doc_name] = content
        
        logger.info(f"[{self.tag}] 🎉 完成 Markdown 文档：{len(generated_docs)}/4")
        
        # 生成 spec_metadata.json（使用规则提取）
        if len(generated_docs) == 4:
            try:
                await self._generate_metadata_json(doc_contents, **kwargs)
            except Exception as e:
                logger.error(f"[{self.tag}] 生成 spec_metadata.json 失败: {e}")
        
        # 返回汇总信息
        summary = f"# Spec Kit 生成完成\n\n生成目录：{self._get_path_manager().spec_kit_dir}\n\n已生成: {len(generated_docs)+1} 个文件"
        return [Message(role='assistant', content=summary)]
    
    async def _generate_metadata_json(self, doc_contents: Dict[str, str], **kwargs) -> None:
        """使用规则提取生成 spec_metadata.json（快速且可靠）"""
        logger.info(f"[{self.tag}] 开始生成 spec_metadata.json（使用规则提取）")
        
        try:
            from src.tools.spec.parser import SpecKitParser
            import json
            
            # 使用 SpecKitParser 解析已生成的文档
            parser = SpecKitParser(self.path_manager.spec_kit_dir)
            
            # 直接设置内容（不需要从文件读取，因为我们已经有内容了）
            parser.spec = doc_contents.get("spec.md", "")
            parser.tasks = doc_contents.get("tasks.md", "")
            
            # 提取模块和任务（方法不接受参数，使用 self.spec 和 self.tasks）
            modules = parser.extract_modules()
            tasks = parser.extract_tasks()
            
            logger.info(f"[{self.tag}] 提取到 {len(modules)} 个模块，{len(tasks)} 个任务")
            
            # 构建 spec_metadata.json
            metadata = {
                "modules": modules,
                "tasks": tasks,
                "task_module_mapping": self._build_task_module_mapping(tasks, modules)
            }
            
            # 保存
            content = json.dumps(metadata, ensure_ascii=False, indent=2)
            self._save_spec_file("spec_metadata.json", content)
            logger.info(f"[{self.tag}] ✅ spec_metadata.json 生成完成")
            
        except Exception as e:
            logger.error(f"[{self.tag}] 生成 spec_metadata.json 失败: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def _build_task_module_mapping(self, tasks: List[Dict], modules: List[Dict]) -> Dict[str, str]:
        """构建任务到模块的映射（简单的关键词匹配）"""
        mapping = {}
        
        for task in tasks:
            task_id = task.get("task_id", "")
            task_desc = task.get("description", "").lower()
            
            # 尝试根据描述匹配模块
            matched_module = None
            for module in modules:
                module_name = module.get("name", "").lower()
                if module_name in task_desc or any(
                    keyword in task_desc 
                    for keyword in module_name.split()
                ):
                    matched_module = module.get("name")
                    break
            
            if matched_module:
                mapping[task_id] = matched_module
        
        return mapping


# 为了兼容配置文件中的 class_name: SpecAgent，提供别名
SpecAgent = SpecGenAgent
