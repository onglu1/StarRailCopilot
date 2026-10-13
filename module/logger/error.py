import os
import re
import time
from datetime import datetime

from module.logger.logger import logger


def save_error_log(config, device, *, png_compress_level=None):
    """
    Save last 60 screenshots in ./log/error/<timestamp>
    Save logs to ./log/error/<timestamp>/log.txt

    Args:
        config: AzurLaneConfig object
        device: Device object
        png_compress_level: Optional lossless PNG compression level.
    """
    from module.base.utils import save_image
    from module.handler.sensitive_info import (handle_sensitive_image, handle_sensitive_logs)
    if config.Error_SaveError:
        folder = f'./log/error/{int(time.time() * 1000)}'
        logger.warning(f'Saving error: {folder}')
        os.makedirs(folder, exist_ok=True)
        for data in device.screenshot_deque:
            image_time = datetime.strftime(data['time'], '%Y-%m-%d_%H-%M-%S-%f')
            image = handle_sensitive_image(data['image'])
            if png_compress_level is None:
                save_image(image, f'{folder}/{image_time}.png')
            else:
                from PIL import Image
                Image.fromarray(image).save(f'{folder}/{image_time}.png', compress_level=png_compress_level)
        if device.screenshot_tracking:
            os.makedirs(f'{folder}/tracking', exist_ok=True)
        for data in device.screenshot_tracking:
            image_time = datetime.strftime(data['time'], '%Y-%m-%d_%H-%M-%S-%f')
            with open(f'{folder}/tracking/{image_time}.png', 'wb') as f:
                f.write(data['image'].getvalue())
        with open(logger.log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            start = 0
            for index, line in enumerate(lines):
                line = line.strip(' \r\t\n')
                if re.match('^═{15,}$', line):
                    start = index
            lines = lines[start - 2:]
            lines = handle_sensitive_logs(lines)
        with open(f'{folder}/log.txt', 'w', encoding='utf-8') as f:
            f.writelines(lines)
