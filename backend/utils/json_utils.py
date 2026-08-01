# backend/utils/json_utils.py
# JSON 处理工具函数

import json

from backend.utils.ai_json import clean_json_response, safe_json_loads


def load_json_file(file_path, default=None):
    """安全加载 JSON 文件"""
    if not file_path.exists():
        return default or {}
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"加载 JSON 文件失败 {file_path}: {e}")
        return default or {}


def save_json_file(file_path, data):
    """安全保存 JSON 文件"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存 JSON 文件失败 {file_path}: {e}")
        return False
