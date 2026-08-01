#!/usr/bin/env python3
"""综合测试：关系系统方案A + ensure_character_fields 自动补全"""
import sys, json
sys.path.insert(0, '.')

from backend.services.relationship_service import (
    parse_relationship_changes,
    build_relationship_string,
    get_current_relationships,
    update_relationships,
    rollback_relationships_to_hour
)
from backend.world_manager import ensure_character_fields


def test_ensure_character_fields_migration():
    """测试 ensure_character_fields 自动补全 relationships_map"""
    print("=== 测试 ensure_character_fields 自动补全 ===")
    
    # 场景1: 有 history 无 map → 自动迁移
    character = {
        "character_id": "test1",
        "world_id": "w1",
        "profile": {"name": "测试"},
        "status": {"is_dead": False, "death_cause": None, "health": 100, "current_scene": "unknown"},
        "relationships_history": [
            {"hour": 10, "content": "赵铁:友好,哈利:崇拜", "timestamp": None},
            {"hour": 5, "content": "赵铁:中立", "timestamp": None}
        ]
    }
    ensure_character_fields(character)
    assert "relationships_map" in character, "未创建 relationships_map"
    assert character["relationships_map"]["赵铁"] == "友好", f"迁移值错误: {character['relationships_map']}"
    assert character["relationships_map"]["哈利"] == "崇拜", f"迁移值错误: {character['relationships_map']}"
    print(f"  ✓ 有history无map → 自动迁移: {character['relationships_map']}")
    
    # 场景2: 无 history 无 map → 设为空字典
    character = {
        "character_id": "test2",
        "world_id": "w1",
        "profile": {"name": "测试"},
        "status": {"is_dead": False, "death_cause": None, "health": 100, "current_scene": "unknown"}
    }
    ensure_character_fields(character)
    assert "relationships_map" in character, "未创建 relationships_map"
    assert character["relationships_map"] == {}, f"应为空字典: {character['relationships_map']}"
    print(f"  ✓ 无history无map → 空字典: {character['relationships_map']}")
    
    # 场景3: 已有 map → 保持不变
    character = {
        "character_id": "test3",
        "world_id": "w1",
        "profile": {"name": "测试"},
        "status": {"is_dead": False, "death_cause": None, "health": 100, "current_scene": "unknown"},
        "relationships_map": {"a": "敌对(旧原因)", "b": "亲密"},
        "relationships_history": [
            {"hour": 10, "content": "a:友好", "timestamp": None}
        ]
    }
    ensure_character_fields(character)
    assert character["relationships_map"]["a"] == "敌对(旧原因)", f"不应覆盖已有值: {character['relationships_map']}"
    assert character["relationships_map"]["b"] == "亲密", f"不应覆盖已有值: {character['relationships_map']}"
    print(f"  ✓ 已有map → 保持不变: {character['relationships_map']}")


def test_full_flow():
    """测试完整流程：加载 → 补全 → 增量更新 → 保存后重新加载"""
    print("\n=== 测试完整流程 ===")
    
    # 模拟旧存档
    character = {
        "character_id": "test4",
        "world_id": "w1",
        "profile": {"name": "测试"},
        "status": {"is_dead": False, "death_cause": None, "health": 100, "current_scene": "unknown"},
        "relationships_history": [
            {"hour": 5, "content": "赵铁:友好,哈利:中立", "timestamp": None}
        ]
    }
    
    # 步骤1: 加载角色（ensure_character_fields 补全字典）
    ensure_character_fields(character)
    rel_map = character["relationships_map"]
    assert rel_map["赵铁"] == "友好" and rel_map["哈利"] == "中立"
    print(f"  ✓ 步骤1 加载补全: {rel_map}")
    
    # 步骤2: 游戏中增量更新（AI只返回变化，含原因）
    update_relationships(character, "哈利:崇拜(被救了)", current_hour=10)
    rel_map = character["relationships_map"]
    assert rel_map["赵铁"] == "友好", f"赵铁不应丢失: {rel_map}"
    assert rel_map["哈利"] == "崇拜(被救了)", f"哈利应更新: {rel_map}"
    print(f"  ✓ 步骤2 增量更新: {rel_map}")
    
    # 步骤3: 新增NPC
    update_relationships(character, "柳青鸾:警惕", current_hour=15)
    rel_map = character["relationships_map"]
    assert "赵铁" in rel_map and "哈利" in rel_map and "柳青鸾" in rel_map
    print(f"  ✓ 步骤3 新增NPC: {rel_map}")
    
    # 步骤4: 验证 history 保存的是完整快照（含原因）
    history = character["relationships_history"]
    latest = history[0]["content"]
    assert "赵铁:友好" in latest and "哈利:崇拜(被救了)" in latest and "柳青鸾:警惕" in latest
    print(f"  ✓ 步骤4 历史快照完整: {latest}")


def test_incremental_edge_cases():
    """测试增量合并的边界情况"""
    print("\n=== 测试增量合并边界 ===")
    
    # 空字符串/null/None 不更新
    character = {
        "relationships_map": {"a": "友好"},
        "relationships_history": []
    }
    update_relationships(character, "", 1)
    update_relationships(character, "null", 2)
    update_relationships(character, None, 3)
    assert character["relationships_map"]["a"] == "友好"
    assert len(character["relationships_history"]) == 0
    print(f"  ✓ null/空/None 不更新")
    
    # 单条更新
    character = {
        "relationships_map": {"a": "友好", "b": "中立"},
        "relationships_history": []
    }
    update_relationships(character, "b:亲密", 5)
    assert character["relationships_map"]["a"] == "友好"
    assert character["relationships_map"]["b"] == "亲密"
    print(f"  ✓ 单条更新保留未变项")
    
    # 多条同时更新
    update_relationships(character, "a:敌对,c:崇拜", 6)
    assert character["relationships_map"]["a"] == "敌对"
    assert character["relationships_map"]["b"] == "亲密"
    assert character["relationships_map"]["c"] == "崇拜"
    print(f"  ✓ 多条更新: {character['relationships_map']}")


def test_rollback():
    """测试回滚"""
    print("\n=== 测试回滚 ===")
    
    character = {
        "relationships_map": {"a": "友好", "b": "亲密"},
        "relationships_history": [
            {"hour": 10, "content": "a:友好,b:亲密", "timestamp": None},
            {"hour": 5, "content": "a:友好,b:中立", "timestamp": None},
            {"hour": 1, "content": "a:中立", "timestamp": None}
        ]
    }
    
    rollback_relationships_to_hour(character, 4)
    assert character["relationships_map"].get("a") == "中立"
    assert "b" not in character["relationships_map"]
    print(f"  ✓ 回滚到hour=4: {character['relationships_map']}")
    
    character = {
        "relationships_map": {"a": "友好", "b": "亲密"},
        "relationships_history": [
            {"hour": 10, "content": "a:友好,b:亲密", "timestamp": None},
            {"hour": 5, "content": "a:友好,b:中立", "timestamp": None},
            {"hour": 1, "content": "a:中立", "timestamp": None}
        ]
    }
    rollback_relationships_to_hour(character, 5)
    assert character["relationships_map"]["a"] == "友好"
    assert character["relationships_map"]["b"] == "中立"
    print(f"  ✓ 回滚到hour=5: {character['relationships_map']}")


def run_all():
    print("="*60)
    print("综合测试：关系系统方案A + ensure_character_fields")
    print("="*60)
    
    try:
        test_ensure_character_fields_migration()
        test_full_flow()
        test_incremental_edge_cases()
        test_rollback()
        
        print("\n" + "="*60)
        print("✅ 所有测试通过！")
        print("="*60)
        return True
    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        return False
    except Exception as e:
        print(f"\n❌ 测试异常: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
