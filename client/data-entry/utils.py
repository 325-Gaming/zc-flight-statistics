from typing import Any, Annotated
from typing import Tuple, Optional, Union

from PIL import Image

def expand_to_square(pil_img, bg_color):
    width, height = pil_img.size
    if width == height:
        result = pil_img
    elif width > height:
        result = Image.new('RGB', (width, width), bg_color)
        result.paste(pil_img, (0, (width - height) // 2))
    else:
        result = Image.new('RGB', (height, height), bg_color)
        result.paste(pil_img, (0, (height - width) // 2))
    return result


def crop_to_16_9_center(img: Image.Image) -> Image.Image:
    """
    将任意比例图片裁剪为16:9（以图片正中心为锚点）

    Args:       
        img: PIL Image对象
    Returns:
        裁剪后的PIL Image对象
    """
    width, height = img.size

    # 计算目标宽高比 (16:9)
    target_ratio = 16 / 9

    # 计算当前宽高比
    current_ratio = width / height

    if current_ratio > target_ratio:
        # 图片太宽，需要裁剪宽度
        new_width = int(height * target_ratio)
        new_height = height
    else:
        # 图片太高，需要裁剪高度
        new_height = int(width / target_ratio)
        new_width = width

    # 计算裁剪区域（以中心为锚点）
    left = (width - new_width) // 2
    top = (height - new_height) // 2
    right = left + new_width
    bottom = top + new_height

    # 裁剪图片
    return img.crop((left, top, right, bottom))


def resize_and_crop_to_16_9(img: Image.Image, target_width: int = 1920) -> Image.Image:
    """
    先调整大小，然后裁剪为16:9

    Args:
        img: PIL Image对象
        target_width: 目标宽度（高度会自动计算为target_width * 9/16）

    Returns:
        处理后的PIL Image对象
    """
    width, height = img.size

    # 计算目标高度（保持16:9比例）
    target_height = int(target_width * 9 / 16)

    # 计算调整大小后的尺寸
    # 先调整到能够包含目标尺寸的最小尺寸
    ratio = max(target_width / width, target_height / height)
    new_width = int(width * ratio)
    new_height = int(height * ratio)

    # 调整图片大小
    resized_img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # 从中心裁剪到目标尺寸
    left = (new_width - target_width) // 2
    top = (new_height - target_height) // 2
    right = left + target_width
    bottom = top + target_height

    return resized_img.crop((left, top, right, bottom))

def process_to_16_9(
    img: Image.Image,
    method: str = 'crop',
    target_width: Optional[int] = None
) -> Image.Image:
    """
    将图片处理为16:9比例的通用函数

    Args:
        img: PIL Image对象
        method: 处理方法
            'crop' - 仅裁剪,
            'resize_crop' - 调整大小后裁剪
        target_width: 目标宽度（仅当method='resize_crop'时有效）

    Returns:
        处理后的PIL Image对象

    Raises:
        ValueError: 当method参数无效时
    """
    width, height = img.size

    if method == 'crop':
        return crop_to_16_9_center(img)

    elif method == 'resize_crop':
        if target_width is None:
            target_width = 1920  # 默认宽度
        return resize_and_crop_to_16_9(img, target_width)

    else:
        raise ValueError("method参数必须是 'crop' 或 'resize_crop'")