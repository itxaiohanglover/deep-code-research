"""反思阶段 Agent：分析测试结果，决定下一步流程跳转

核心职责：
1. 从 spec_code_mapping.json 读取测试结果
2. 调用 LLM 分析测试结果，区分设计缺陷和实现缺陷
3. 根据分析结果决定下一步流程跳转

流程跳转逻辑（通过 next_flow() 方法）：
- 测试全部通过 → 继续到 summary (idx + 1)
- 设计缺陷 → 回退到 requirements
- 实现缺陷 → 回退到 coding
- 无测试记录 → 回退到 testing 重新生成测试

设计原则：
- 工作流索引从配置动态解析，避免硬编码
- 使用 workflow_manager 获取 Agent 索引
"""
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

from ms_agent.llm.utils import Message
from ms_agent.utils import get_logger

from src.agents._base_agent import BaseAgent
from src.prompts.reflecting_prompts import build_reflecting_prompt
from src.utils.workflow_manager import workflow_manager

logger = get_logger()


class ReflectingAgent(BaseAgent):
    """反思阶段 Agent
    
    职责：
    1. 从 spec_code_mapping.json 读取测试结果
    2. 调用 LLM 分析测试结果，区分设计缺陷和实现缺陷
    3. 根据分析结果决定下一步流程跳转
    
    流程跳转目标（从 workflow.yaml 动态获取索引）：
    - requirements: 设计缺陷回退目标
    - coding: 实现缺陷回退目标
    - testing: 无测试记录回退目标
    
    最大迭代限制：
    - 默认最大迭代次数为 3 次
    - 超过限制后强制进入 summary 阶段，防止无限循环
    - 可通过环境变量 MAX_WORKFLOW_ITERATIONS 修改
    """
    
    # 跳转目标 Agent 名称（与 workflow.yaml 中的 key 对应）
    REQUIREMENTS_AGENT = "requirements"  # phase2：设计缺陷
    CODING_AGENT = "coding"              # phase3：实现缺陷
    TESTING_AGENT = "testing"            # 无测试记录
    
    # 最大迭代次数限制（防止无限循环）
    # 可通过环境变量 MAX_WORKFLOW_ITERATIONS 覆盖
    DEFAULT_MAX_ITERATIONS = 3

    def __init__(self, config, tag: str = "reflecting", **kwargs):
        super().__init__(config, tag, **kwargs)
        
        # SpecCodeTracker 由 ArtifactStoreMixin 统一管理，直接使用 self.tracker
        
        # 流程控制状态（在 run() 中设置）
        self.all_tests_passed: bool = False
        self.next_phase: Optional[str] = None  # "phase2" | "phase3" | "summary"
    
    def _load_test_results(self) -> Dict:
        """从 spec_code_mapping.json 加载测试结果
        
        Returns:
            {
                "all_tests": [...],      # 所有测试
                "failed_tests": [...],   # 失败的测试
                "all_passed": bool,      # 是否全部通过
                "total": int,
                "passed": int,
                "failed": int
            }
        """
        all_tests = []
        failed_tests = []
        
        # 从 tracker 读取 code_to_test 映射
        code_to_test = self.tracker.mapping.get("code_to_test", {})
        
        for code_file, tests in code_to_test.items():
            spec_task_id = self.tracker.get_spec_for_code(code_file)
            
            for test_info in tests:
                result = test_info.get("result", {})
                test_data = {
                    "code_file": code_file,
                    "spec_task_id": spec_task_id,
                    "test_script": test_info.get("test_script", ""),
                    "success": result.get("success", True),
                    "output": result.get("output", ""),
                }
                all_tests.append(test_data)
                if not test_data["success"]:
                    failed_tests.append(test_data)
        
        # 注意：如果没有任何测试，不应判定为"全部通过"
        # 应该是"无测试"状态，需要回退到 coding 重新生成测试
        has_tests = len(all_tests) > 0
        total = len(all_tests)
        passed = total - len(failed_tests)
        
        # 通过率计算：超过 90% 即判定为通过
        pass_rate = (passed / total * 100) if total > 0 else 0
        all_passed = has_tests and pass_rate >= 90.0
        
        return {
            "all_tests": all_tests,
            "failed_tests": failed_tests,
            "all_passed": all_passed,
            "has_tests": has_tests,
            "total": total,
            "passed": passed,
            "failed": len(failed_tests),
            "pass_rate": pass_rate
        }
    
    def _get_spec_code_mapping(self) -> Dict:
        """获取 Spec-Code 映射验证信息
        
        Returns:
            包含 mapped, unmapped, partial 三个列表的字典
        """
        try:
            mapping = self.tracker.verify_mapping()
            return mapping
        except Exception as e:
            logger.warning(f"[{self.tag}] 获取 Spec-Code 映射验证失败: {e}")
            return {"mapped": [], "unmapped": [], "partial": []}
    
    def _build_prompt(self, user_input: str) -> str:
        """构建发送给 LLM 的提示词"""
        test_results = self._load_test_results()
        
        # 获取 Spec-Code 映射验证信息
        mapping_info = self._get_spec_code_mapping()
        
        # 使用 prompts 模块构建提示词
        return build_reflecting_prompt(
            test_results=test_results,
            mapping_info=mapping_info
        )
    
    def _parse_llm_output(self, output: str) -> Dict:
        """从 LLM 输出中解析 JSON
        
        解析策略：
        1. 优先从 ```json ``` 代码块中提取
        2. 尝试找到完整的 JSON 对象（匹配括号）
        3. 如果都失败，返回空字典并设置默认行为
        
        Returns:
            {"next_phase": "phase2|phase3|summary", "reason": "..."}
        """
        if not output:
            return {}
        
        # 尝试从 ```json ``` 代码块中提取
        json_match = re.search(r'```json\s*(\{.*?\})\s*```', output, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # 尝试解析完整 JSON 对象（使用括号匹配）
        try:
            start = output.find('{')
            if start >= 0:
                # 使用括号匹配找到完整的 JSON
                depth = 0
                for i, char in enumerate(output[start:], start):
                    if char == '{':
                        depth += 1
                    elif char == '}':
                        depth -= 1
                        if depth == 0:
                            return json.loads(output[start:i + 1])
        except json.JSONDecodeError as e:
            logger.warning(f"[{self.tag}] JSON 解析失败: {e}")
        
        return {}
    
    async def run(self, inputs: Any, **kwargs: Any) -> Any:
        """运行 Agent"""
        logger.info(f"[{self.tag}] 开始反思分析")
        
        # 1. 加载测试结果
        test_results = self._load_test_results()
        self.all_tests_passed = test_results['all_passed']
        
        if not test_results['has_tests']:
            logger.warning(f"[{self.tag}] 没有测试记录，将回退到 testing 阶段重新生成测试")
        else:
            pass_rate = test_results.get('pass_rate', 0)
            logger.info(f"[{self.tag}] 测试结果: {test_results['passed']}/{test_results['total']} 通过 (通过率: {pass_rate:.1f}%)")
        
        # 2. 调用 LLM 分析
        llm_result = await super().run(inputs, **kwargs)
        
        # 3. 提取 LLM 输出文本
        llm_output = ""
        if isinstance(llm_result, str):
            llm_output = llm_result
        elif isinstance(llm_result, list) and llm_result:
            last_msg = llm_result[-1]
            if hasattr(last_msg, 'content'):
                llm_output = last_msg.content
            elif isinstance(last_msg, dict):
                llm_output = last_msg.get('content', '')
        
        # 4. 解析 LLM 输出
        parsed = self._parse_llm_output(llm_output)
        
        if not test_results['has_tests']:
            # 没有测试 → 回退到 testing 阶段生成测试
            self.next_phase = "testing"
            logger.info(f"[{self.tag}] 无测试记录，回退到 testing")
        elif self.all_tests_passed:
            self.next_phase = "summary"
        else:
            # 从 LLM 输出获取 next_phase，默认为 phase3（实现缺陷）
            self.next_phase = parsed.get("next_phase", "phase3")
        
        # 5. 保存状态到文件
        self._save_status()
        
        # 6. 如果需要回退，保存回退上下文供目标 Agent 使用
        if self.next_phase not in ("summary", None):
            self._save_rollback_context(test_results, parsed)
        
        logger.info(f"[{self.tag}] 分析完成: next_phase={self.next_phase}")
        
        # 6. 返回报告
        report = self._generate_report(test_results, parsed)
        return [Message(role="assistant", content=report)]
    
    def _save_status(self):
        """保存流程控制状态
        
        同时保存到：
        1. WorkflowContext（推荐，集中管理）
        2. 独立文件（向后兼容）
        """
        # 1. 保存到 WorkflowContext
        if workflow_manager.context:
            workflow_manager.context.metadata["reflection"] = {
                "all_tests_passed": self.all_tests_passed,
                "next_phase": self.next_phase,
                "timestamp": datetime.now().isoformat()
            }
            workflow_manager.save_context()
            logger.debug(f"[{self.tag}] 状态已保存到 WorkflowContext")
        
        # 2. 保存到独立文件（向后兼容）
        session_dir = self.path_manager.repo_dir.parent
        status_file = session_dir / "reflection_status.json"
        
        status = {
            "all_tests_passed": self.all_tests_passed,
            "next_phase": self.next_phase,
            "timestamp": datetime.now().isoformat()
        }
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
            status_file.write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info(f"[{self.tag}] 已保存状态: {status_file}")
        except Exception as e:
            logger.warning(f"[{self.tag}] 保存状态失败: {e}")
    
    def _save_rollback_context(self, test_results: Dict, parsed: Dict):
        """保存回退上下文，供目标 Agent 读取错误信息
        
        Args:
            test_results: 测试结果
            parsed: LLM 解析的分析结果
        """
        # 确定目标 Agent
        target_agent_map = {
            "phase2": self.REQUIREMENTS_AGENT,
            "phase3": self.CODING_AGENT,
            "testing": self.TESTING_AGENT,
        }
        target_agent = target_agent_map.get(self.next_phase, self.CODING_AGENT)
        
        # 构建回退上下文
        rollback_context = {
            "target_agent": target_agent,
            "reason": parsed.get("reason", "测试未通过"),
            "defect_type": parsed.get("defect_type", "implementation"),
            "pass_rate": test_results.get("pass_rate", 0),
            "failed_count": test_results.get("failed", 0),
            "total_count": test_results.get("total", 0),
            "failed_tests": [],
            "error_analysis": parsed.get("analysis", ""),
            "suggestions": parsed.get("suggestions", []),
            "iteration": workflow_manager.get_iteration(),
        }
        
        # 提取失败测试的详细信息
        for test in test_results.get("failed_tests", [])[:5]:  # 最多 5 个
            rollback_context["failed_tests"].append({
                "code_file": test.get("code_file", ""),
                "spec_task_id": test.get("spec_task_id", ""),
                "error_output": test.get("output", "")[:500],  # 截断过长的输出
            })
        
        # 保存到 WorkflowContext
        workflow_manager.set_rollback_context(rollback_context)
        logger.info(f"[{self.tag}] 已保存回退上下文: target={target_agent}, reason={rollback_context['reason']}")
    
    def _load_status(self):
        """加载流程控制状态
        
        优先从 WorkflowContext 加载，其次从独立文件加载。
        """
        # 1. 尝试从 WorkflowContext 加载
        if workflow_manager.context:
            reflection = workflow_manager.context.metadata.get("reflection", {})
            if reflection:
                self.all_tests_passed = reflection.get("all_tests_passed", False)
                self.next_phase = reflection.get("next_phase")
                logger.debug(f"[{self.tag}] 从 WorkflowContext 加载状态")
                return
        
        # 2. 从独立文件加载（向后兼容）
        session_dir = self.path_manager.repo_dir.parent
        status_file = session_dir / "reflection_status.json"
        
        if status_file.exists():
            try:
                status = json.loads(status_file.read_text(encoding="utf-8"))
                self.all_tests_passed = status.get("all_tests_passed", False)
                self.next_phase = status.get("next_phase")
            except Exception as e:
                logger.warning(f"[{self.tag}] 加载状态失败: {e}")
    
    def _generate_report(self, test_results: Dict, parsed: Dict) -> str:
        """生成用户友好的报告"""
        pass_rate = test_results.get('pass_rate', 0)
        
        # 状态文字
        if not test_results.get('has_tests', False):
            status_text = "⚠️ 无测试记录"
        elif self.all_tests_passed:
            status_text = f"✅ 通过 (通过率: {pass_rate:.1f}% ≥ 90%)"
        else:
            status_text = f"❌ 未达标 (通过率: {pass_rate:.1f}% < 90%)"
        
        report = f"""# 反思报告

## 测试结果概览

- 总测试数: {test_results['total']}
- 通过: {test_results['passed']}
- 失败: {test_results['failed']}
- 通过率: {pass_rate:.1f}%
- 状态: {status_text}

## 分析结论

"""
        if not test_results.get('has_tests', False):
            report += "没有测试记录，将回退到 **Testing** 阶段生成测试。\n"
        elif self.all_tests_passed:
            report += f"测试通过率达到 {pass_rate:.1f}%（≥90%），将进入 **Summary** 阶段生成 Agent Skill。\n"
        elif self.next_phase == "phase2":
            report += f"""检测到 **设计缺陷**，需要回退到 **Requirements** 阶段重新设计。

**原因**: {parsed.get('reason', '未提供')}
"""
        else:
            report += f"""检测到 **实现缺陷**（通过率 {pass_rate:.1f}% < 90%），需要回退到 **Coding** 阶段修复代码。

**原因**: {parsed.get('reason', '未提供')}
"""
        return report
    
    def _get_agent_index(self, agent_name: str) -> int:
        """获取 Agent 的工作流索引（从配置动态解析）
        
        Args:
            agent_name: Agent 名称
            
        Returns:
            Agent 索引，如果未找到则返回 -1
        """
        return workflow_manager.get_agent_index(agent_name)
    
    def _get_max_iterations(self) -> int:
        """获取最大迭代次数限制
        
        优先从环境变量 MAX_WORKFLOW_ITERATIONS 读取，
        否则使用默认值 DEFAULT_MAX_ITERATIONS。
        
        Returns:
            最大迭代次数
        """
        try:
            return int(os.getenv("MAX_WORKFLOW_ITERATIONS", self.DEFAULT_MAX_ITERATIONS))
        except (ValueError, TypeError):
            return self.DEFAULT_MAX_ITERATIONS
    
    def next_flow(self, idx: int) -> int:
        """决定下一步跳转到哪个 agent
        
        ChainWorkflow 约束：
        - 可以回退到任意之前的 agent（返回值 < idx）
        - 可以继续到下一个（返回值 = idx + 1）
        - 不能跳过中间的 agent（返回值 > idx + 1 会失败）
        
        最大迭代限制：
        - 超过 MAX_WORKFLOW_ITERATIONS 次后强制进入 summary
        - 防止无限循环导致的资源浪费
        
        Args:
            idx: 当前 agent 在工作流链中的索引
            
        Returns:
            下一个 agent 的索引
        """
        # 如果内存中没有状态，从文件加载
        if self.next_phase is None:
            self._load_status()
        
        # 检查是否超过最大迭代次数限制
        current_iteration = workflow_manager.get_iteration()
        max_iterations = self._get_max_iterations()
        
        if current_iteration >= max_iterations and self.next_phase not in ("summary", None):
            if not self.all_tests_passed:
                logger.warning(
                    f"[{self.tag}] ⚠️ 已达到最大迭代次数限制 ({current_iteration}/{max_iterations})，"
                    f"强制进入 summary 阶段。原计划: {self.next_phase}"
                )
                # 记录强制跳转决策
                workflow_manager.record_flow_decision(
                    from_agent=self.tag,
                    to_agent="summary",
                    reason=f"达到最大迭代次数限制 ({max_iterations})",
                    decision_type="forced"
                )
                return idx + 1  # 强制进入 summary
        
        # 根据 next_phase 决定跳转
        if self.all_tests_passed or self.next_phase == "summary":
            # 测试通过 → 继续到 summary
            target_agent = "summary"
            target_idx = idx + 1
            decision_type = "normal"
            reason = "所有测试通过"
            logger.info(f"[{self.tag}] 测试通过，继续到 {target_agent} (idx={target_idx})")
        
        elif self.next_phase == "phase2":
            # 设计缺陷 → 回退到 requirements
            target_agent = self.REQUIREMENTS_AGENT
            target_idx = self._get_agent_index(target_agent)
            target_idx = target_idx if target_idx >= 0 else 0
            decision_type = "rollback"
            reason = "设计缺陷"
            logger.info(f"[{self.tag}] 设计缺陷，回退到 {target_agent} (idx={target_idx})")
        
        elif self.next_phase == "testing":
            # 无测试记录 → 回退到 testing 重新生成测试
            target_agent = self.TESTING_AGENT
            target_idx = self._get_agent_index(target_agent)
            target_idx = target_idx if target_idx >= 0 else idx - 1
            decision_type = "rollback"
            reason = "无测试记录"
            logger.info(f"[{self.tag}] 无测试记录，回退到 {target_agent} (idx={target_idx})")
        
        else:  # phase3 或其他
            # 实现缺陷 → 回退到 coding
            target_agent = self.CODING_AGENT
            target_idx = self._get_agent_index(target_agent)
            target_idx = target_idx if target_idx >= 0 else idx - 2
            decision_type = "rollback"
            reason = "实现缺陷"
            logger.info(f"[{self.tag}] 实现缺陷，回退到 {target_agent} (idx={target_idx})")
        
        # 记录流程跳转决策到 WorkflowContext
        workflow_manager.record_flow_decision(
            from_agent=self.tag,
            to_agent=target_agent,
            reason=reason,
            decision_type=decision_type
        )
        
        return target_idx
