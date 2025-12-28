"""Spec Kit 和代码关联追踪器

建立和维护 Spec Kit -> Repo -> Result 的映射关系。
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from ms_agent.utils import get_logger

logger = get_logger()


class SpecCodeTracker:
    """Spec Kit 和代码关联追踪器
    
    功能：
    1. 建立 Spec Kit 任务/模块 -> 代码文件的映射
    2. 建立代码文件 -> 测试结果的映射
    3. 查询和验证映射关系
    """
    
    def __init__(self, base_dir: Path):
        """初始化追踪器
        
        Args:
            base_dir: 基础目录路径（通常是 output/{session_id} 或 output）
        """
        self.base_dir = Path(base_dir)
        self.spec_kit_dir = self.base_dir / "spec_kit"
        self.repo_dir = self.base_dir / "repo"
        self.mapping_file = self.base_dir / "spec_code_mapping.json"
        
        # 加载现有映射
        self.mapping = self._load_mapping()
    
    def _load_mapping(self) -> Dict:
        """加载映射文件"""
        if self.mapping_file.exists():
            try:
                return json.loads(self.mapping_file.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"[SpecCodeTracker] 加载映射文件失败: {e}")
        
        return {
            "spec_to_code": {},  # spec_task_id -> [code_files]
            "code_to_spec": {},  # code_file -> spec_task_id
            "code_to_test": {},  # code_file -> test_result
            "test_results": {}   # test_script -> test_result
        }
    
    def _save_mapping(self):
        """保存映射文件"""
        try:
            self.mapping_file.parent.mkdir(parents=True, exist_ok=True)
            self.mapping_file.write_text(
                json.dumps(self.mapping, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            logger.info(f"[SpecCodeTracker] 已保存映射文件: {self.mapping_file}")
        except Exception as e:
            logger.error(f"[SpecCodeTracker] 保存映射文件失败: {e}")
    
    def add_spec_code_mapping(self, spec_task_id: str, code_files: List[str]):
        """添加 Spec Kit 任务到代码文件的映射
        
        Args:
            spec_task_id: Spec Kit 任务 ID（如 task_1, module_1）
            code_files: 代码文件路径列表（相对于 repo 目录）
        """
        if spec_task_id not in self.mapping["spec_to_code"]:
            self.mapping["spec_to_code"][spec_task_id] = []
        
        for code_file in code_files:
            # 标准化路径
            code_file = str(Path(code_file).as_posix())
            
            if code_file not in self.mapping["spec_to_code"][spec_task_id]:
                self.mapping["spec_to_code"][spec_task_id].append(code_file)
            
            # 建立反向映射
            self.mapping["code_to_spec"][code_file] = spec_task_id
        
        self._save_mapping()
        logger.info(f"[SpecCodeTracker] 已添加映射: {spec_task_id} -> {code_files}")
    
    def add_test_result(self, code_file: str, test_script: str, test_result: Dict):
        """添加测试结果
        
        Args:
            code_file: 代码文件路径
            test_script: 测试脚本路径或命令
            test_result: 测试结果（包含 success, output 等）
        """
        code_file = str(Path(code_file).as_posix())
        
        if code_file not in self.mapping["code_to_test"]:
            self.mapping["code_to_test"][code_file] = []
        
        self.mapping["code_to_test"][code_file].append({
            "test_script": test_script,
            "result": test_result
        })
        
        # 保存测试结果
        self.mapping["test_results"][test_script] = test_result
        
        self._save_mapping()
        logger.info(f"[SpecCodeTracker] 已添加测试结果: {code_file} -> {test_script}")
    
    def get_code_for_task(self, task_id: str) -> List[str]:
        """获取实现某个任务的代码文件
        
        Args:
            task_id: Spec Kit 任务 ID
        
        Returns:
            代码文件路径列表
        """
        return self.mapping["spec_to_code"].get(task_id, [])
    
    def get_spec_for_code(self, file_path: str) -> Optional[str]:
        """获取代码对应的 Spec Kit 任务 ID
        
        Args:
            file_path: 代码文件路径
        
        Returns:
            Spec Kit 任务 ID，如果不存在返回 None
        """
        file_path = str(Path(file_path).as_posix())
        return self.mapping["code_to_spec"].get(file_path)
    
    def get_test_results_for_code(self, file_path: str) -> List[Dict]:
        """获取代码文件的测试结果
        
        Args:
            file_path: 代码文件路径
        
        Returns:
            测试结果列表
        """
        file_path = str(Path(file_path).as_posix())
        return self.mapping["code_to_test"].get(file_path, [])
    
    def verify_mapping(self) -> Dict:
        """验证 Spec Kit 和代码的对应关系
        
        Returns:
            验证结果字典，包含 mapped, unmapped, partial 三个列表
        """
        # 加载 Spec Kit 元数据
        spec_metadata_file = self.spec_kit_dir / "spec_metadata.json"
        if not spec_metadata_file.exists():
            return {
                "mapped": [],
                "unmapped": [],
                "partial": []
            }
        
        try:
            spec_metadata = json.loads(spec_metadata_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[SpecCodeTracker] 加载 Spec 元数据失败: {e}")
            return {
                "mapped": [],
                "unmapped": [],
                "partial": []
            }
        
        # 获取所有任务
        all_tasks = []
        if "tasks" in spec_metadata:
            all_tasks = [task.get("id") for task in spec_metadata["tasks"]]
        
        mapped = []
        unmapped = []
        partial = []
        
        for task_id in all_tasks:
            code_files = self.get_code_for_task(task_id)
            if len(code_files) > 0:
                # 检查是否有测试结果
                has_test = any(
                    len(self.get_test_results_for_code(code_file)) > 0
                    for code_file in code_files
                )
                if has_test:
                    mapped.append({
                        "task_id": task_id,
                        "code_files": code_files,
                        "status": "complete"
                    })
                else:
                    partial.append({
                        "task_id": task_id,
                        "code_files": code_files,
                        "status": "no_test"
                    })
            else:
                unmapped.append({
                    "task_id": task_id,
                    "code_files": [],
                    "status": "no_code"
                })
        
        return {
            "mapped": mapped,
            "unmapped": unmapped,
            "partial": partial
        }
