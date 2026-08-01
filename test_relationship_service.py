#!/usr/bin/env python3
"""测试 relationship_service.py 方案A实现"""
import sys
sys.path.insert(0, '.')

from backend.services.relationship_service import (
    parse_relationship_changes,
    build_relationship_string,
    get_current_relationships,
    update_relationships,
    rollback_relationships_to_hour
)


def test_parse():
    """测试解析函数"""
    print("=== 测试 parse_relationship_changes ===")
    
    # 基础格式
    r = parse_relationship_changes("赵铁:友好,哈利:崇拜")
    assert r == {"赵铁": "友好", "哈利": "崇拜"}, f"基础解析失败: {r}"
    print(f"  ✓ 基础解析: {r}")
    
    # 带原因
    r = parse_relationship_changes("赵铁:敌对(当众辱骂),柳青鸾:轻视")
    assert r == {"赵铁": "敌对", "柳青鸾": "轻视"}, f"带原因解析失败: {r}"
    print(f"  ✓ 带原因解析: {r}")
    
    # 空/null
    r = parse_relationship_changes("")
    assert r == {}, f"空解析失败: {r}"
    r = parse_relationship_changes("null")
    assert r == {}, f"null解析失败: {r}"
    print(f"  ✓ 空/null解析正确")
    
    # 单条
    r = parse_relationship_changes("张三:热恋")
    assert r == {"张三": "热恋"}, f"单条解析失败: {r}"
    print(f"  ✓ 单条解析: {r}")


def test_build():
    """测试构建函数"""
    print("\n=== 测试 build_relationship_string ===")
    
    s = build_relationship_string({"赵铁": "友好", "哈利": "崇拜"})
    assert "赵铁:友好" in s and "哈利:崇拜" in s, f"构建失败: {s}"
    print(f"  ✓ 构建: {s}")
    
    s = build_relationship_string({})
    assert s == "", f"空构建失败: {s}"
    print(f"  ✓ 空字典构建: '{s}'")


def test_get_current_from_dict():
    """测试从字典获取关系集合"""
    print("\n=== 测试 get_current_relationships（字典模式）===")
    
    character = {
        "relationships_map": {"赵铁": "友好", "哈利": "崇拜"}
    }
    s = get_current_relationships(character)
    assert "赵铁:友好" in s and "哈利:崇拜" in s, f"字典获取失败: {s}"
    print(f"  ✓ 从字典获取: {s}")


def test_migration_from_old_data():
    """测试旧数据迁移"""
    print("\n=== 测试旧数据迁移 ===")
    
    character = {
        "relationships_history": [
            {"hour": 10, "content": "赵铁:友好,哈利:崇拜", "timestamp": None},
            {"hour": 5, "content": "赵铁:中立", "timestamp": None}
        ]
    }
    s = get_current_relationships(character)
    assert "赵铁:友好" in s and "哈利:崇拜" in s, f"迁移失败: {s}"
    assert "relationships_map" in character, "迁移后未创建字典"
    assert character["relationships_map"]["赵铁"] == "友好"
    assert character["relationships_map"]["哈利"] == "崇拜"
    print(f"  ✓ 旧数据迁移成功: {s}")
    print(f"  ✓ 迁移后字典: {character['relationships_map']}")


def test_incremental_update():
    """测试增量更新：核心场景"""
    print("\n=== 测试增量更新（核心） ===")
    
    # 场景1: 原a友好,b中立 → 更新b友好 → a保留,b更新
    character = {
        "relationships_map": {"a": "友好", "b": "中立"},
        "relationships_history": []
    }
    update_relationships(character, "b:友好", current_hour=10)
    rel_map = character["relationships_map"]
    assert rel_map["a"] == "友好", f"场景1 a丢失: {rel_map}"
    assert rel_map["b"] == "友好", f"场景1 b未更新: {rel_map}"
    print(f"  ✓ 场景1（更新b，保留a）: {rel_map}")
    
    # 场景2: 原a友好,b中立 → 更新c中立 → a,b,c都在
    character = {
        "relationships_map": {"a": "友好", "b": "中立"},
        "relationships_history": []
    }
    update_relationships(character, "c:中立", current_hour=11)
    rel_map = character["relationships_map"]
    assert "a" in rel_map and rel_map["a"] == "友好", f"场景2 a丢失: {rel_map}"
    assert "b" in rel_map and rel_map["b"] == "中立", f"场景2 b丢失: {rel_map}"
    assert "c" in rel_map and rel_map["c"] == "中立", f"场景2 c未添加: {rel_map}"
    print(f"  ✓ 场景2（新增c，保留a,b）: {rel_map}")
    
    # 场景3: 多条同时变化
    character = {
        "relationships_map": {"a": "友好", "b": "中立", "c": "崇拜"},
        "relationships_history": []
    }
    update_relationships(character, "a:敌对,b:亲密", current_hour=12)
    rel_map = character["relationships_map"]
    assert rel_map["a"] == "敌对", f"场景3 a未更新: {rel_map}"
    assert rel_map["b"] == "亲密", f"场景3 b未更新: {rel_map}"
    assert rel_map["c"] == "崇拜", f"场景3 c丢失: {rel_map}"
    print(f"  ✓ 场景3（多NPC同时变化，保留未变c）: {rel_map}")
    
    # 场景4: null/空字符串不更新
    character = {
        "relationships_map": {"a": "友好"},
        "relationships_history": []
    }
    update_relationships(character, "null", current_hour=13)
    update_relationships(character, "", current_hour=13)
    update_relationships(character, None, current_hour=13)
    rel_map = character["relationships_map"]
    assert rel_map["a"] == "友好", f"场景4 被null覆盖: {rel_map}"
    print(f"  ✓ 场景4（null/空不更新）: {rel_map}")
    
    # 验证历史记录保存的是完整快照
    history = character["relationships_history"]
    assert len(history) == 0, f"场景4不应产生历史: {history}"  # null不产生历史
    print(f"  ✓ null不产生历史记录")


def test_history_snapshot():
    """测试历史快照是否完整"""
    print("\n=== 测试历史快照 ===")
    
    character = {
        "relationships_map": {"a": "友好", "b": "中立"},
        "relationships_history": []
    }
    update_relationships(character, "b:亲密", current_hour=20)
    
    history = character["relationships_history"]
    assert len(history) == 1, f"历史条数不对: {len(history)}"
    snapshot = history[0]["content"]
    assert "a:友好" in snapshot and "b:亲密" in snapshot, f"快照不完整: {snapshot}"
    print(f"  ✓ 历史快照完整: {snapshot}")


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
    # 回滚到 hour=4：历史中有 hour=1 (a:中立)，这是 <=4 的最新记录
    rollback_relationships_to_hour(character, 4)
    rel_map = character["relationships_map"]
    assert rel_map.get("a") == "中立", f"回滚后a错误: {rel_map}"
    assert "b" not in rel_map, f"回滚后b不应存在: {rel_map}"
    print(f"  ✓ 回滚到hour=4（取hour=1记录）: {rel_map}")
    
    # 回滚到 hour=5：应取 hour=5 的 a:友好,b:中立
    character = {
        "relationships_map": {"a": "友好", "b": "亲密"},
        "relationships_history": [
            {"hour": 10, "content": "a:友好,b:亲密", "timestamp": None},
            {"hour": 5, "content": "a:友好,b:中立", "timestamp": None},
            {"hour": 1, "content": "a:中立", "timestamp": None}
        ]
    }
    rollback_relationships_to_hour(character, 5)
    rel_map = character["relationships_map"]
    assert rel_map.get("a") == "友好", f"回滚到5后a错误: {rel_map}"
    assert rel_map.get("b") == "中立", f"回滚到5后b错误: {rel_map}"
    print(f"  ✓ 回滚到hour=5（取hour=5记录）: {rel_map}")


def run_all():
    print("="*60)
    print("开始测试 relationship_service 方案A")
    print("="*60)
    
    try:
        test_parse()
        test_build()
        test_get_current_from_dict()
        test_migration_from_old_data()
        test_incremental_update()
        test_history_snapshot()
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
