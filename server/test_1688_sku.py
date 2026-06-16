import json
import sys
from pathlib import Path
from typing import Any


FILE_PATH = Path(r"E:\e-commerce-project\EasyCollect\server\static\cache_data\raw_payload.json")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def safe_get(data: Any, path: list[str]) -> Any:
    current = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def find_global_data(raw_data: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        ["globalData"],
        ["result", "global", "globalData"],
        ["result", "data", "globalData"],
        ["data", "globalData"],
    ]

    for path in candidates:
        value = safe_get(raw_data, path)
        if isinstance(value, dict) and value:
            print(f"✅ 命中 globalData 路径: {'.'.join(path)}")
            return value

    return {}


def find_sku_model(global_data: dict[str, Any], raw_data: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        ["skuModel"],
        ["model", "skuModel"],
        ["model", "tradeModel"],
        ["model", "tradeModel", "skuModel"],
    ]

    for path in candidates:
        value = safe_get(global_data, path)
        if isinstance(value, dict) and value:
            print(f"✅ 命中 skuModel 路径: globalData.{'.'.join(path)}")
            return value

    raw_candidates = [
        ["skuModel"],
        ["result", "data", "Root", "fields", "dataJson", "skuModel"],
        ["result", "global", "globalData", "model", "skuModel"],
        ["result", "global", "globalData", "model", "tradeModel"],
    ]
    for path in raw_candidates:
        value = safe_get(raw_data, path)
        if isinstance(value, dict) and value:
            print(f"✅ 命中 skuModel 路径: {'.'.join(path)}")
            return value

    return {}


def looks_like_image(value: Any) -> bool:
    if not isinstance(value, str):
        return False

    lowered = value.lower()
    return any(marker in lowered for marker in ["http", ".jpg", ".jpeg", ".png", ".webp", "img/ibank"])


def print_image_like_fields(node: dict[str, Any], indent: str = "    ") -> None:
    for key, value in node.items():
        if looks_like_image(value):
            print(f"{indent}🌟 发现疑似图片链接! 键名: [{key}], 值: {value}")


def find_nodes_by_key(data: Any, target_keys: set[str]) -> list[tuple[str, Any]]:
    matches: list[tuple[str, Any]] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child_path = f"{path}.{key}" if path else key
                if key in target_keys:
                    matches.append((child_path, value))
                if isinstance(value, (dict, list)):
                    walk(value, child_path)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                if isinstance(item, (dict, list)):
                    walk(item, f"{path}[{index}]")

    walk(data, "")
    return matches


def print_sku_props_node(sku_props: Any, path: str) -> None:
    print(f"\n--- skuProps 路径: {path} ---")
    if not isinstance(sku_props, list) or not sku_props:
        print(f"⚠️ 节点不是非空列表，类型={type(sku_props).__name__}, 值预览={str(sku_props)[:300]}")
        return

    for prop_index, prop in enumerate(sku_props):
        if not isinstance(prop, dict):
            print(f"属性维度 #{prop_index}: 非 dict 节点，类型={type(prop).__name__}")
            continue

        prop_name = prop.get("prop") or prop.get("name") or prop.get("propName")
        print(f"属性维度 #{prop_index}: {prop_name}")
        print(f"  - 维度自身键名: {list(prop.keys())}")
        print_image_like_fields(prop, indent="    ")

        values = (
            prop.get("value")
            or prop.get("values")
            or prop.get("propertyValues")
            or prop.get("propValues")
            or prop.get("optionList")
            or []
        )
        if isinstance(values, dict):
            values = list(values.values())

        if not isinstance(values, list) or not values:
            print("  ⚠️ 该维度未找到 value/values/propertyValues/propValues/optionList。")
            continue

        for value_index, val in enumerate(values):
            if not isinstance(val, dict):
                print(f"  - 选项 #{value_index}: 非 dict 节点，值: {val}")
                continue

            option_name = val.get("name") or val.get("value") or val.get("title")
            print(f"  - 选项 #{value_index}: {option_name} | 所有键名: {list(val.keys())}")
            print_image_like_fields(val, indent="    ")


def print_sku_map_node(sku_map: Any, path: str) -> None:
    print(f"\n--- SKU Map 路径: {path} ---")
    if not isinstance(sku_map, dict) or not sku_map:
        print(f"⚠️ 节点不是非空 dict，类型={type(sku_map).__name__}, 值预览={str(sku_map)[:300]}")
        return

    for spec, details in list(sku_map.items())[:5]:
        print(f"组合键: {spec}")
        if not isinstance(details, dict):
            print(f"  - 非 dict 明细，类型={type(details).__name__}, 值={details}")
            continue

        print(f"  - 包含的键名: {list(details.keys())}")
        print_image_like_fields(details, indent="    ")


def sniff_sku_structure() -> None:
    try:
        with FILE_PATH.open("r", encoding="utf-8") as file:
            raw_data = json.load(file)

        if not isinstance(raw_data, dict):
            print("❌ raw_payload.json 顶层不是 dict，无法按 1688 商品结构解析。")
            return

        global_data = find_global_data(raw_data)
        if not global_data:
            print("❌ 未找到 globalData，这可能是另一种页面模板！")
            print("当前的顶层 keys:", list(raw_data.keys()))
            return

        sku_model = find_sku_model(global_data, raw_data)
        if not isinstance(sku_model, dict) or not sku_model:
            print("❌ globalData 中未找到 skuModel。")
            print("globalData keys:", list(global_data.keys()))
            model = global_data.get("model")
            if isinstance(model, dict):
                print("globalData.model keys:", list(model.keys()))
            return

        print("====== 🔍 1. 嗅探 skuProps (属性定义层) ======")
        sku_props = sku_model.get("skuProps", [])
        if isinstance(sku_props, list) and sku_props:
            print_sku_props_node(sku_props, "selected_sku_model.skuProps")
        else:
            print("⚠️ 当前 skuModel.skuProps 为空，开始递归搜索所有 skuProps。")
            sku_props_nodes = find_nodes_by_key(raw_data, {"skuProps"})
            if not sku_props_nodes:
                print("❌ 全量 raw_data 中也没有发现 skuProps。")
            for path, node in sku_props_nodes[:8]:
                print_sku_props_node(node, path)

        print("\n====== 🔍 2. 嗅探 skuMap (变体组合层) ======")
        sku_map = (
            sku_model.get("skuMap")
            or sku_model.get("skuInfoMap")
            or sku_model.get("skuMapOriginal")
            or sku_model.get("skuInfoMapOriginal")
            or {}
        )

        if not isinstance(sku_map, dict) or not sku_map:
            print("⚠️ 当前 skuModel.skuMap/skuInfoMap 为空，开始递归搜索所有 SKU Map。")
            sku_map_nodes = find_nodes_by_key(
                raw_data,
                {"skuMap", "skuInfoMap", "skuMapOriginal", "skuInfoMapOriginal"},
            )
            if not sku_map_nodes:
                print("❌ 全量 raw_data 中也没有发现 SKU Map。")
            for path, node in sku_map_nodes[:8]:
                print_sku_map_node(node, path)
        else:
            print_sku_map_node(sku_map, "selected_sku_model.skuMap")

        print("\n====== 🔍 3. skuModel 顶层 keys ======")
        print(list(sku_model.keys()))

    except FileNotFoundError:
        print(f"❌ 文件不存在: {FILE_PATH}")
    except json.JSONDecodeError as exc:
        print(f"❌ JSON 解析失败: {exc}")
    except Exception as exc:
        print(f"执行出错: {exc}")


if __name__ == "__main__":
    sniff_sku_structure()
