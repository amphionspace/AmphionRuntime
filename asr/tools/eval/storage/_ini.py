"""凭证文件定位 —— 三个对象存储客户端共用。

凭证本身不入库：运行时从 ini 读取（段名 cos / obs / sensecore，键 access_key /
secret_key）。ini 路径按以下顺序解析，第一个非空者生效：

    1) 客户端各自的旧环境变量（COS_INI / OBS_INI / AOSS_INI）
    2) AMPHION_STORAGE_INI
    3) ~/project/amphionbucket/storage.ini（本机既有约定）
"""
import os
from pathlib import Path

DEFAULT = Path.home() / "project" / "amphionbucket" / "storage.ini"


def ini_path(legacy_env=None):
    for key in ([legacy_env] if legacy_env else []) + ["AMPHION_STORAGE_INI"]:
        value = os.environ.get(key)
        if value:
            return value
    return str(DEFAULT)


def remotes_json():
    """build.json（记录各 bucket/endpoint 的清单）路径，与 ini 同目录。"""
    return os.environ.get(
        "AMPHION_REMOTES_JSON", str(Path(ini_path()).parent / "build.json"))
