"""VLM 服务 - 通过 API 调用视觉语言模型

复用 LLM 的 API 调用模式，支持 OpenAI 兼容接口。
模型配置从配置文件读取。

注意：
- 默认使用 Tencent-Hunyuan/HunyuanOCR 模型（ModelScope API）
- 需要配置 MODELSCOPE_API_KEY 环境变量
"""

from __future__ import annotations

import os
import base64
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from omegaconf import DictConfig

try:
    from ms_agent.utils import get_logger
    logger = get_logger()
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


class VLMService:
    """视觉语言模型服务
    
    通过 OpenAI 兼容 API 调用 VLM 模型。
    
    默认使用 ModelScope API + HunyuanOCR 模型。
    
    配置示例 (yaml):
    ```yaml
    vlm:
      model: Qwen/Qwen3-VL-8B-Instruct
      api_key: ${oc.env:MODELSCOPE_API_KEY}
      base_url: https://api-inference.modelscope.cn/v1
      max_tokens: 1024
    ```
    
    使用方式：
    ```python
    vlm = VLMService(config)
    description = await vlm.describe_image("path/to/image.png")
    ```
    """
    
    # 支持的图片格式
    SUPPORTED_FORMATS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
    
    # 默认使用 ModelScope API + Qwen3-VL 模型
    # 注意: 8B 模型速度快，235B 模型更准但很慢
    # DEFAULT_MODEL = 'Qwen/Qwen3-VL-235B-A22B-Instruct'
    DEFAULT_MODEL = 'Qwen/Qwen3-VL-8B-Instruct'
    DEFAULT_BASE_URL = 'https://api-inference.modelscope.cn/v1'
    
    def __init__(self, config: DictConfig = None):
        """初始化 VLM 服务
        
        Args:
            config: 配置对象，包含 vlm 或 llm 配置
        """
        self.config = config
        self._client = None
        self._initialized = False
        self._available = None  # None 表示未检测，True/False 表示检测结果
        
        # 读取 VLM 配置（优先使用专门的 vlm 配置，否则复用 llm 配置）
        vlm_cfg = getattr(config, 'vlm', None) if config else None
        llm_cfg = getattr(config, 'llm', {}) if config else {}
        
        if vlm_cfg:
            # 使用专门的 VLM 配置
            self.model = getattr(vlm_cfg, 'model', None) or self.DEFAULT_MODEL
            self.api_key = getattr(vlm_cfg, 'api_key', None) or getattr(vlm_cfg, 'dashscope_api_key', None)
            self.base_url = getattr(vlm_cfg, 'base_url', None) or getattr(vlm_cfg, 'dashscope_base_url', None)
            self.max_tokens = int(getattr(vlm_cfg, 'max_tokens', 1024))
        else:
            # 复用 LLM 配置，使用默认 VLM 模型
            self.model = self.DEFAULT_MODEL
            self.api_key = None
            self.base_url = None
            self.max_tokens = 1024
        
        # 从环境变量获取（如果配置中没有）
        # 优先使用 ModelScope API
        if not self.api_key:
            self.api_key = os.getenv('MODELSCOPE_API_KEY') or os.getenv('DASHSCOPE_API_KEY')
        if not self.base_url:
            self.base_url = os.getenv('MODELSCOPE_BASE_URL') or self.DEFAULT_BASE_URL
    
    def _init_client(self):
        """懒加载初始化 OpenAI 客户端"""
        if self._initialized:
            return
        
        if not self.api_key:
            logger.warning("[vlm_service] 未配置 API Key")
            return
        
        try:
            from openai import OpenAI
            
            # 确保 base_url 以 /v1 结尾
            base_url = self.base_url
            if base_url and not base_url.endswith('/v1'):
                base_url = base_url.rstrip('/') + '/v1'
            
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=base_url
            )
            self._initialized = True
            logger.info(f"[vlm_service] 初始化成功: model={self.model}, base_url={base_url}")
            
        except ImportError:
            logger.error("[vlm_service] openai 库未安装")
        except Exception as e:
            logger.error(f"[vlm_service] 初始化失败: {e}")
    
    def _encode_image(self, image_path: str, max_size_mb: float = 4.0) -> Optional[str]:
        """将图片编码为 base64，如果图片太大则压缩
        
        Args:
            image_path: 图片路径
            max_size_mb: 最大图片大小（MB），超过会压缩，默认 4MB
            
        Returns:
            base64 编码的图片数据 URL，失败返回 None
        """
        path = Path(image_path)
        
        if not path.exists():
            logger.warning(f"[vlm_service] 图片不存在: {image_path}")
            return None
        
        ext = path.suffix.lower()
        if ext not in self.SUPPORTED_FORMATS:
            logger.warning(f"[vlm_service] 不支持的图片格式: {ext}")
            return None
        
        # 确定 MIME 类型
        mime_types = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.bmp': 'image/bmp'
        }
        mime_type = mime_types.get(ext, 'image/jpeg')
        
        try:
            file_size_mb = path.stat().st_size / (1024 * 1024)
            
            # 如果图片太大，尝试压缩
            if file_size_mb > max_size_mb:
                logger.info(f"[vlm_service] 图片较大 ({file_size_mb:.1f}MB)，尝试压缩...")
                compressed_data = self._compress_image(path, max_size_mb)
                if compressed_data:
                    image_data = base64.b64encode(compressed_data).decode('utf-8')
                    return f"data:{mime_type};base64,{image_data}"
                else:
                    logger.warning(f"[vlm_service] 图片压缩失败，使用原图")
            
            # 读取原图
            with open(path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            return f"data:{mime_type};base64,{image_data}"
            
        except Exception as e:
            logger.error(f"[vlm_service] 读取图片失败: {e}")
            return None
    
    def _compress_image(self, image_path: Path, target_size_mb: float) -> Optional[bytes]:
        """压缩图片到目标大小
        
        Args:
            image_path: 图片路径
            target_size_mb: 目标大小（MB）
            
        Returns:
            压缩后的图片字节，失败返回 None
        """
        try:
            from PIL import Image
            import io
            
            # 打开图片
            img = Image.open(image_path)
            
            # 计算目标尺寸（保持宽高比）
            target_bytes = int(target_size_mb * 1024 * 1024)
            quality = 85
            
            # 如果图片很大，先缩小尺寸
            max_dimension = 2048
            if max(img.size) > max_dimension:
                ratio = max_dimension / max(img.size)
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            
            # 转换为 RGB（如果是 RGBA）
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            
            # 压缩到目标大小
            output = io.BytesIO()
            img.save(output, format='JPEG', quality=quality, optimize=True)
            
            # 如果还是太大，降低质量
            while output.tell() > target_bytes and quality > 30:
                quality -= 10
                output.seek(0)
                output.truncate()
                img.save(output, format='JPEG', quality=quality, optimize=True)
            
            return output.getvalue()
            
        except ImportError:
            logger.debug("[vlm_service] PIL 未安装，无法压缩图片")
            return None
        except Exception as e:
            logger.debug(f"[vlm_service] 图片压缩失败: {e}")
            return None
    
    async def describe_image(
        self,
        image_path: str,
        prompt: str = "请详细描述这张图片的内容，包括关键的技术要点、图表信息、文字内容等。",
        detail: str = "auto"
    ) -> str:
        """描述图片内容
        
        Args:
            image_path: 图片路径
            prompt: 描述提示词
            detail: 图片细节级别 (low/high/auto)
            
        Returns:
            图片描述文本
        """
        self._init_client()
        
        if not self._client:
            return "[VLM 服务不可用]"
        
        # 编码图片
        image_url = self._encode_image(image_path)
        if not image_url:
            return f"[无法读取图片: {image_path}]"
        
        try:
            # 构建消息（OpenAI VLM 格式）
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url,
                                "detail": detail
                            }
                        }
                    ]
                }
            ]
            
            import time
            start_time = time.time()
            print(f"[vlm_service] 开始调用 API: {start_time}")
            # 调用 API
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens,
            )

            end_time = time.time()
            logger.info(f"[vlm_service] API 调用时间: {end_time - start_time}秒")
            # 提取响应内容
            if response.choices and len(response.choices) > 0:
                content = response.choices[0].message.content
                return content.strip() if content else "[图片描述为空]"
            
            return "[未获取到图片描述]"
            
        except Exception as e:
            logger.error(f"[vlm_service] API 调用失败: {e}")
            return f"[VLM 调用失败: {str(e)}]"
    
    async def analyze_images(
        self,
        image_paths: List[str],
        prompt: str = "请分析这些图片的内容和它们之间的关系。"
    ) -> str:
        """分析多张图片
        
        Args:
            image_paths: 图片路径列表
            prompt: 分析提示词
            
        Returns:
            分析结果文本
        """
        self._init_client()
        
        if not self._client:
            return "[VLM 服务不可用]"
        
        # 构建内容列表
        content = [{"type": "text", "text": prompt}]
        
        for path in image_paths:
            image_url = self._encode_image(path)
            if image_url:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })
        
        if len(content) == 1:
            return "[没有有效的图片可分析]"
        
        try:
            messages = [{"role": "user", "content": content}]
            
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=self.max_tokens
            )
            
            if response.choices and len(response.choices) > 0:
                result_content = response.choices[0].message.content
                return result_content.strip() if result_content else "[分析结果为空]"
            
            return "[未获取到分析结果]"
            
        except Exception as e:
            logger.error(f"[vlm_service] 多图分析失败: {e}")
            return f"[VLM 调用失败: {str(e)}]"
    
    def describe(self, image_path: str, prompt: str = "请描述图片的技术要点", timeout: int = 120) -> str:
        """同步版本的图片描述（兼容旧接口）
        
        简化版本：直接调用异步方法，使用 asyncio.run
        
        Args:
            image_path: 图片路径
            prompt: 描述提示词
            timeout: 超时时间（秒），默认 120 秒
            
        Returns:
            图片描述文本，失败返回空字符串
        """
        import asyncio
        import concurrent.futures
        
        try:
            # 尝试获取当前事件循环
            try:
                loop = asyncio.get_running_loop()
                # 如果已经在事件循环中，使用线程池执行
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self.describe_image(image_path, prompt)
                    )
                    return future.result(timeout=timeout)
            except RuntimeError:
                # 没有运行中的事件循环，直接使用 asyncio.run
                return asyncio.run(
                    asyncio.wait_for(
                        self.describe_image(image_path, prompt),
                        timeout=timeout
                    )
                )
                
        except (asyncio.TimeoutError, concurrent.futures.TimeoutError):
            logger.warning(f"[vlm_service] 调用超时 ({timeout}s): {image_path}")
            return ""
        except Exception as e:
            logger.debug(f"[vlm_service] 同步调用失败: {e}")
            return ""
