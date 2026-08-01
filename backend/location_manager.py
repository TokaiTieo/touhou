# backend/location_manager.py

import json
import uuid
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field


@dataclass
class Location:
    """地点数据类"""
    id: str
    name: str
    parent: Optional[str]
    type: str  # 'region' or 'scene'
    description: str
    icon: str = "📍"
    is_base: bool = True
    discovered_from: Optional[str] = None
    discovered_at: Optional[str] = None
    discovered_by: Optional[str] = None
    unlock_status: str = "unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        return result
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Location':
        return cls(**data)


class LocationManager:
    """地点管理器 - 统一管理基础地点和动态地点（支持动态世界路径）"""
    
    def __init__(self, locations_dir: Path):
        """
        初始化地点管理器
        locations_dir: 当前世界的地点目录（如 worlds/default/locations/）
        """
        self.locations_dir = Path(locations_dir)
        self.locations_dir.mkdir(parents=True, exist_ok=True)
        
        self.base_file = self.locations_dir / "location_base.json"
        self.dynamic_file = self.locations_dir / "location_dynamic.json"
        
        self._base_locations: Dict[str, Location] = {}
        self._dynamic_locations: Dict[str, Location] = {}
        self._regions: Dict[str, Location] = {}
        
        self._load_all()
    
    def _load_all(self):
        """加载所有地点"""
        self._base_locations = self._load_file(self.base_file, is_base=True)
        self._dynamic_locations = self._load_file(self.dynamic_file, is_base=False)
        self._build_region_index()
    
    def _load_file(self, file_path: Path, is_base: bool) -> Dict[str, Location]:
        """加载单个地点文件"""
        locations = {}
        if file_path.exists():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    for region_data in data.get('regions', []):
                        loc = Location(
                            id=region_data['id'],
                            name=region_data['name'],
                            parent=None,
                            type='region',
                            description=region_data.get('description', ''),
                            icon=region_data.get('icon', '🏛️'),
                            is_base=is_base
                        )
                        locations[loc.id] = loc
                    
                    for loc_data in data.get('locations', []):
                        loc = Location(
                            id=loc_data['id'],
                            name=loc_data['name'],
                            parent=loc_data.get('parent'),
                            type='scene',
                            description=loc_data.get('description', ''),
                            icon=loc_data.get('icon', '📍'),
                            is_base=is_base,
                            discovered_from=loc_data.get('discovered_from'),
                            discovered_at=loc_data.get('discovered_at'),
                            discovered_by=loc_data.get('discovered_by'),
                            metadata={
                                "danger_level": loc_data.get("danger_level", "未知"),
                                "danger_note": loc_data.get("danger_note", ""),
                                "main_rewards": loc_data.get("main_rewards", "")
                            }
                        )
                        locations[loc.id] = loc
            except Exception as e:
                print(f"加载地点文件失败 {file_path}: {e}")
        return locations
    
    def _build_region_index(self):
        """构建区域索引"""
        all_locs = self.get_all_locations()
        self._regions = {loc.id: loc for loc in all_locs.values() if loc.type == 'region'}
    
    def _save_base_file(self):
        """保存基础地点文件"""
        self._save_file(self.base_file, self._base_locations, is_base=True)
    
    def _save_dynamic_file(self):
        """保存动态地点文件"""
        self._save_file(self.dynamic_file, self._dynamic_locations, is_base=False)
    
    def _save_file(self, file_path: Path, locations: Dict[str, Location], is_base: bool):
        """保存地点到文件"""
        regions = []
        location_list = []
        
        for loc in locations.values():
            if loc.type == 'region':
                regions.append({
                    "id": loc.id,
                    "name": loc.name,
                    "type": "region",
                    "description": loc.description,
                    "icon": loc.icon
                })
            else:
                loc_dict = {
                    "id": loc.id,
                    "name": loc.name,
                    "parent": loc.parent,
                    "type": loc.type,
                    "description": loc.description,
                    "icon": loc.icon,
                    "danger_level": loc.metadata.get("danger_level", "未知"),
                    "danger_note": loc.metadata.get("danger_note", ""),
                    "main_rewards": loc.metadata.get("main_rewards", "")
                }
                if not is_base:
                    loc_dict["discovered_from"] = loc.discovered_from
                    loc_dict["discovered_at"] = loc.discovered_at
                    loc_dict["discovered_by"] = loc.discovered_by
                location_list.append(loc_dict)
        
        data = {
            "version": 1,
            "last_updated": datetime.now().isoformat(),
            "regions": regions,
            "locations": location_list
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def get_all_locations(self) -> Dict[str, Location]:
        """获取所有地点（基础+动态）"""
        all_locs = {}
        all_locs.update(self._base_locations)
        all_locs.update(self._dynamic_locations)
        return all_locs
    
    def get_location(self, location_id: str) -> Optional[Location]:
        """获取单个地点"""
        all_locs = self.get_all_locations()
        return all_locs.get(location_id)
    
    def get_location_by_name(self, name: str) -> Optional[Location]:
        """根据名称获取地点（包括区域和场景）"""
        all_locs = self.get_all_locations()
        
        for loc in all_locs.values():
            loc_name = loc.name if hasattr(loc, 'name') else loc.get('name')
            if loc_name == name:
                return loc
        
        for loc_id, loc in all_locs.items():
            if loc_id == name:
                return loc
        
        return None
    
    def get_location_tree(self, unlocked_ids: List[str] = None) -> List[Dict]:
        """构建地点树"""
        all_locs = self.get_all_locations()
        
        locations_by_parent = {}
        regions = {}
        
        for loc in all_locs.values():
            if loc.type == 'region':
                regions[loc.id] = loc
            elif loc.parent:
                if loc.parent not in locations_by_parent:
                    locations_by_parent[loc.parent] = []
                locations_by_parent[loc.parent].append(loc)
        
        tree = []
        for region_id, region in regions.items():
            region_locations = locations_by_parent.get(region_id, [])
            
            if unlocked_ids:
                region_locations = [loc for loc in region_locations if loc.id in unlocked_ids]
            
            if region_locations:
                tree.append({
                    "id": region_id,
                    "name": region.name,
                    "type": "region",
                    "icon": region.icon,
                    "description": region.description,
                    "locations": [
                        {
                            "id": loc.id,
                            "name": loc.name,
                            "description": loc.description,
                            "icon": loc.icon,
                            "is_base": loc.is_base,
                            "unlock_status": loc.unlock_status
                        }
                        for loc in region_locations
                    ]
                })
        
        return tree
    
    def add_dynamic_location(self, name: str, parent: str, description: str = "",
                            icon: str = "🔍", discovered_from: str = None,
                            discovered_by: str = None) -> Location:
        """添加动态发现的地点"""
        existing = self.get_location_by_name(name)
        if existing:
            print(f"  地点已存在: {name}")
            return existing
        
        location_id = f"dynamic_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        
        new_location = Location(
            id=location_id,
            name=name,
            parent=parent,
            type="scene",
            description=description or f"在{discovered_from}发现的地点",
            icon=icon,
            is_base=False,
            discovered_from=discovered_from,
            discovered_at=datetime.now().isoformat(),
            discovered_by=discovered_by,
            unlock_status="entered"
        )
        
        self._dynamic_locations[location_id] = new_location
        self._save_dynamic_file()
        
        print(f"  ✓ 动态地点已添加: {name} (ID: {location_id})")
        return new_location
    
    def add_location(self, location_data: Dict) -> Optional[Location]:
        """添加地点（兼容性包装方法）"""
        return self.add_dynamic_location(
            name=location_data.get("name"),
            parent=location_data.get("parent"),
            description=location_data.get("description", ""),
            icon=location_data.get("icon", "🔍"),
            discovered_from=location_data.get("discovered_from", "chapter"),
            discovered_by=location_data.get("discovered_by", "system")
        )
    
    def location_exists(self, name: str) -> bool:
        """检查地点是否存在"""
        return self.get_location_by_name(name) is not None
    
    def update_location_status(self, location_id: str, status: str):
        """更新地点状态"""
        all_locs = self.get_all_locations()
        if location_id in all_locs:
            all_locs[location_id].unlock_status = status
            if location_id in self._base_locations:
                self._save_base_file()
            elif location_id in self._dynamic_locations:
                self._save_dynamic_file()


# ========== 全局实例 ==========
_location_manager = None


def get_location_manager(locations_dir: Path) -> LocationManager:
    """获取地点管理器实例"""
    global _location_manager
    _location_manager = LocationManager(locations_dir)
    return _location_manager
