# Copyright (c) Alibaba, Inc. and its affiliates.
import os
from pathlib import Path
from typing import Any, Dict, Optional, List

from ms_agent.llm.utils import Tool
from ms_agent.tools.base import ToolBase
from ms_agent.utils import get_logger


from ms_enclave.sandbox.manager import LocalSandboxManager
from ms_enclave.sandbox.model import DockerSandboxConfig, SandboxType

logger = get_logger()

DEFAULT_OUTPUT_DIR=os.getenv("OUTPUT_DIR", "output")

class SandboxTool(ToolBase):
    """A sandbox execution tool based on ms-enclave LocalSandboxManager.

    功能：
    - 为当前项目的 output_dir（或 config 指定）启动一个持久化的 Docker sandbox；
    - 在该 sandbox 里执行任意 Linux shell 命令（cd / ls / cat / test 等）；
    - 支持指定项目子目录（如 frontend / backend），自动 cd 到 /workspace/<folder> 再执行；
    - 保证同一个 output_dir 只复用同一个容器，不会每次调用都重新起容器、重装依赖。

    典型用法（由大模型通过 tool-calling 发起）：
    - 在 frontend 目录下安装依赖：
      command = "npm install", folder = "frontend"

    - 在 backend 目录下运行测试：
      command = "npm test", folder = "backend"

    - 在项目根列出文件：
      command = "ls", folder = "" 或 None

    注意：
    - 容器内 /workspace 映射到宿主机的 output_dir（包含 session_id）。
    - 所有命令默认在 /workspace 或 /workspace/<folder> 下执行。
    """

    def __init__(self, config, **kwargs):
        super(SandboxTool, self).__init__(config)

        # 支持通过 config.tools.sandbox.exclude_functions 之类屏蔽部分工具
        sandbox_config = getattr(config.tools, "sandbox", None) if hasattr(config, 'tools') else None
        if sandbox_config is not None:
            self.exclude_func(sandbox_config)

        # 使用 config.output_dir（已经包含 session_id）
        # ConfigHandler 已经设置 config.output_dir = "output/{session_id}/"
        # 所以这里直接使用即可
        self.output_dir = getattr(config, 'output_dir', None)
        if not self.output_dir:
            # 后备方案：从环境变量获取
            session_id = os.getenv("SESSION_ID")
            base_output_dir = os.getenv("OUTPUT_DIR", "output")
            if session_id:
                self.output_dir = str(Path(base_output_dir) / session_id)
            else:
                self.output_dir = base_output_dir
        
        session_id = os.getenv("SESSION_ID")
        
        logger.info(f"[SandboxTool] output_dir: {self.output_dir} (session_id={session_id})")

        # sandbox 相关配置
        # self._sandbox_image: str = getattr(config, "sandbox_image", "node:20")
        self._sandbox_image: str = getattr(config, "sandbox_image", "python:3.11-slim")
        self._network_enabled: bool = getattr(
            config, "sandbox_network_enabled", True
        )
        # 容器内挂载根路径，/workspace 会对应 host 的 output_dir
        self._sandbox_container_root: str = getattr(
            config, "sandbox_container_root", "/workspace"
        )
        # ms-enclave 需要告知有哪些 tools 可用，这里只用 shell_executor
        self._sandbox_tools_config = {"shell_executor": {}}

        # --- runtime 状态 ---
        self._sandbox_manager: Optional[LocalSandboxManager] = None
        self._sandbox_id: Optional[str] = None
        self._sandbox_host_root: Optional[str] = None

    # ----------------------------------------------------------------------
    # 基础生命周期
    # ----------------------------------------------------------------------
    async def connect(self):
        """初始化 LocalSandboxManager（懒加载）。

        与 FileSystemTool 保持接口一致：agent 初始化时会调用一次 connect()。
        """
        if self._sandbox_manager is None:
            logger.info("[SandboxTool] Initializing LocalSandboxManager ...")
            self._sandbox_manager = LocalSandboxManager()
            # 手动进入 async context
            await self._sandbox_manager.__aenter__()
            logger.info("[SandboxTool] LocalSandboxManager initialized.")

    async def _ensure_sandbox(self):
        """确保为当前 output_dir 创建并复用一个 sandbox。

        - 如果已经有 sandbox 且挂载的 host_root 与当前 output_dir 一致，则直接复用；
        - 否则停止 / 删除旧 sandbox，并为新的 output_dir 创建一个 sandbox。
        """
        await self.connect()
        assert self._sandbox_manager is not None

        host_output_dir = self._get_host_output_dir()

        # 已有 sandbox 且 output_dir 未变，直接复用
        if (
            self._sandbox_id is not None
            and self._sandbox_host_root == host_output_dir
        ):
            return

        # output_dir 变了，或者首次创建
        if self._sandbox_id is not None:
            try:
                await self._sandbox_manager.stop_sandbox(self._sandbox_id)
            except Exception:
                logger.exception(
                    "[SandboxTool] Failed to stop existing sandbox"
                )
            try:
                await self._sandbox_manager.delete_sandbox(self._sandbox_id)
            except Exception:
                logger.exception(
                    "[SandboxTool] Failed to delete existing sandbox"
                )
            self._sandbox_id = None

        # 确保 host 端目录存在
        os.makedirs(host_output_dir, exist_ok=True)

        # 创建新的 sandbox
        # DockerSandboxConfig 的 command 和 network 参数有默认值，无需显式传递
        sandbox_config = DockerSandboxConfig(  # pyright: ignore[reportCallIssue]
            image=self._sandbox_image,
            tools_config=self._sandbox_tools_config,
            # 将 host 的 output_dir 映射到容器内 /workspace
            volumes={
                host_output_dir: {
                    "bind": self._sandbox_container_root,
                    "mode": "rw",
                }
            },
            network_enabled=self._network_enabled,
            remove_on_exit=True,
        )

        self._sandbox_id = await self._sandbox_manager.create_sandbox(
            SandboxType.DOCKER, sandbox_config
        )
        self._sandbox_host_root = host_output_dir
       # src 、、、REAMD、test
        logger.info(
            f"[SandboxTool] Created sandbox: id={self._sandbox_id}, "
            f"host_root={host_output_dir}, "
            f"container_root={self._sandbox_container_root}, "
            f"image={self._sandbox_image}"
        )

    async def _teardown_sandbox(self):
        """可选的清理方法（当前工具内部不会自动调用，一般在进程退出时统一处理即可）。"""
        if self._sandbox_manager is None:
            return

        if self._sandbox_id is not None:
            try:
                await self._sandbox_manager.stop_sandbox(self._sandbox_id)
            except Exception:
                logger.exception(
                    "[SandboxTool] Failed to stop sandbox during teardown"
                )
            try:
                await self._sandbox_manager.delete_sandbox(self._sandbox_id)
            except Exception:
                logger.exception(
                    "[SandboxTool] Failed to delete sandbox during teardown"
                )
            self._sandbox_id = None

        try:
            await self._sandbox_manager.__aexit__(None, None, None)
        except Exception:
            logger.exception(
                "[SandboxTool] Failed to close LocalSandboxManager"
            )
        finally:
            self._sandbox_manager = None
            self._sandbox_host_root = None

    def _get_host_output_dir(self) -> str:
        """获取当前 config 对应的 host 端 output_dir（绝对路径）。"""
        return os.path.abspath(self.output_dir or DEFAULT_OUTPUT_DIR)

    def _container_project_path(self, folder: Optional[str] = None) -> str:
        """容器内项目路径，例如 /workspace 或 /workspace/frontend。"""
        root = self._sandbox_container_root.rstrip("/")
        if folder:
            return f"{root}/{folder}"
        return root

    # ----------------------------------------------------------------------
    # 工具声明（暴露给大模型的 Tool 列表）
    # ----------------------------------------------------------------------
    async def get_tools(self):
        """返回工具声明，格式与 FileSystemTool 一致。"""
        tools = {
            "sandbox": [
                Tool(
                    tool_name="run_shell_command",
                    server_name="sandbox",
                    description=(
                        "Run an arbitrary Linux shell command inside a "
                        "persistent Docker sandbox. "
                        "The sandbox is bound to the project's output_dir "
                        "so that installed dependencies (e.g. npm install) "
                        "are preserved across calls.\n\n"
                        "Typical usage:\n"
                        "- npm install in frontend: command='npm install', folder='frontend'\n"
                        "- run tests in backend: command='npm test', folder='backend'\n"
                        "- list files in project root: command='ls', folder=''"
                    ),
                    parameters={
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": (
                                    "The shell command to execute inside the "
                                    "sandbox (e.g. 'npm install', "
                                    "'npm run build', 'ls', 'cat package.json')."
                                ),
                            },
                            "folder": {
                                "type": "string",
                                "description": (
                                    "Optional project subdirectory under the "
                                    "mounted /workspace. "
                                    "If provided, the tool will run "
                                    "`cd /workspace/<folder> && <command>`.\n"
                                    "Examples: 'frontend', 'backend'. "
                                    "If omitted or empty, the command runs "
                                    "under /workspace."
                                ),
                            },
                            "timeout": {
                                "type": "integer",
                                "description": (
                                    "Optional timeout in seconds for the "
                                    "command execution. Default is 300."
                                ),
                            },
                        },
                        "required": ["command"],
                        "additionalProperties": False,
                    },
                ),
            ]
        }

        return {
            "sandbox": [
                t
                for t in tools["sandbox"]
                if t["tool_name"] not in self.exclude_functions
            ]
        }

    async def call_tool(
        self, server_name: str, *, tool_name: str, tool_args: Dict[str, Any]
    ) -> str:
        """与 FileSystemTool 一致的调度入口。"""
        # 目前只有一个 server_name="sandbox"
        if server_name != "sandbox":
            raise ValueError(f"Unsupported server_name: {server_name}")
        return await getattr(self, tool_name)(**tool_args)

    # ----------------------------------------------------------------------
    # 对外暴露的实际工具方法
    # ----------------------------------------------------------------------
    async def run_shell_command(
        self,
        command: str,
        folder: Optional[str] = None,
        timeout: int = 300,
    ) -> str:
        """在 sandbox 内执行一条 shell 命令。

        Args:
            command: 要执行的 shell 命令，例如 'npm install'、'npm run build'、'ls' 等。
            folder: 可选，项目子目录名称。若提供，将在 /workspace/<folder> 下执行。
            timeout: 命令执行超时时间（秒），默认 300。

        Returns:
            命令的 stdout / stderr / error 等拼接后的文本结果。
        """
        return await self._run_shell(command, folder=folder, timeout=timeout)

    # ----------------------------------------------------------------------
    # 内部执行逻辑（复用你原来的 _run_shell 思路）
    # ----------------------------------------------------------------------
    async def _run_shell(
        self, cmd: str, folder: Optional[str] = None, timeout: int = 300
    ) -> str:
        """
        在 sandbox 内通过 shell_executor 执行命令。

        使用 /bin/sh -c 'cd work_dir && cmd' 的形式，
        以保证 'cd' 等 shell 内建可用，同时默认进入 /workspace 或 /workspace/<folder>。
        """
        await self._ensure_sandbox()
        assert (
            self._sandbox_manager is not None and self._sandbox_id is not None
        )

        # 计算容器内的工作目录，如 /workspace/frontend
        work_dir = self._container_project_path(folder)

        # 拼出带 cd 的完整命令
        full_cmd = f"cd {work_dir} && {cmd}"

        # 用 /bin/sh -c 包一层，保证 shell 内建命令可用
        # 同时对单引号做转义，避免打断 sh -c 的字符串
        safe_cmd_str = full_cmd.replace("'", "'\"'\"'")
        final_exec = f"/bin/sh -c '{safe_cmd_str}'"

        logger.info(f"[SandboxTool] Exec Request: {final_exec}")

        try:
            result = await self._sandbox_manager.execute_tool(
                self._sandbox_id,
                "shell_executor",
                {"command": final_exec, "timeout": timeout},
            )
        except Exception as e:
            # 这里是 sandbox 自身执行失败（例如 docker 失败）
            msg = (
                "[SandboxTool] Error when running command in sandbox: "
                f"{e!r}"
            )
            logger.exception(msg)
            return msg

        # 尽量从 result 中抽出输出信息
        parts: List[str] = []

        # 常见字段：output / stdout / stderr / error
        for attr in ("output", "stdout", "stderr", "error"):
            value = getattr(result, attr, None)
            if value:
                parts.append(str(value))

        # 有些工具结果是 pydantic model，可以 model_dump
        if not parts and hasattr(result, "model_dump"):
            try:
                parts.append(str(result.model_dump()))
            except Exception:
                pass

        # 有些情况下可能是 dict
        if not parts and isinstance(result, dict):
            parts.append(str(result))

        if not parts:
            parts.append(repr(result))

        output = "\n".join(parts)



        return output
