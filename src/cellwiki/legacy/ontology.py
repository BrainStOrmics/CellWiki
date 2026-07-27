# =============================================================================
# 细胞本体论 —— 细胞本体论加载、解析和细胞类型名称解析
# =============================================================================
# 提供 OBO 文件解析、手动 ID 映射和精确的细胞类型匹配（无模糊匹配）。
# 设计为在开发期间能优雅处理本体论文件缺失的情况。
# 匹配优先级：手动修正 → 手动注册表 → 精确匹配 → 归一化匹配。
# =============================================================================

"""Cell Ontology loading, parsing, and cell type name resolution.

Provides OBO file parsing, manual ID mapping, and fuzzy-free cell type matching.
Designed to be robust against missing ontology files during development."""

import json
import re
from pathlib import Path
from cellwiki.config import settings


# ---------------------------------------------------------------------------
# 加载并解析 OBO 格式的细胞本体论文件
# OBO（Open Biomedical Ontologies）是生物医学领域常用的本体论格式。
# 返回结构化字典，包含 terms（术语详情）和 synonym_map（同义词到 CL ID 的映射）。
# 如果文件不存在，优雅降级返回空字典，避免阻塞开发流程。
# ---------------------------------------------------------------------------
def load_cell_ontology(obo_path: str | Path | None = None) -> dict:
    """Parse an OBO file into structured data.

    Returns:
    {
        "terms": {
            "CL:0000003": {
                "name": "native cell",
                "is_a": ["CL:0000000"],
                "synonyms": ["native cell"],
                "definition": "...",
            },
            ...
        },
        "synonym_map": {
            "native cell": "CL:0000003",
            ...
        },
    }
    """
    # 如果未指定路径，使用配置中的默认路径
    if obo_path is None:
        obo_path = settings.cell_ontology_file

    obo_path = Path(obo_path)
    # 如果本体论文件不存在，打印警告并返回空字典
    # 这样在开发环境中即使没有本体论文件，模块也能正常导入
    if not obo_path.exists():
        print(f"Warning: Cell Ontology file not found at {obo_path}")
        print("Run 'cellwiki init' or 'python scripts/download_ontology.py' first.")
        return {"terms": {}, "synonym_map": {}}

    terms = {}
    synonym_map = {}

    # 一次性读取整个 OBO 文件到内存
    with open(obo_path, encoding="utf-8") as f:
        content = f.read()

    # 按 [Term] 标记分割成独立的术语块
    # 分割后的第一个元素是文件头（非术语行），会被安全跳过
    # 因为它不会匹配下面的 "id:" 模式
    stanzas = re.split(r"\n\[Term\]\n", content)

    # 遍历每个术语块，解析其中的字段
    for stanza in stanzas:
        lines = stanza.strip().split("\n")
        term_id = None
        name = None
        is_a = []
        synonyms = []
        definition = ""

        # 逐行解析 OBO 术语的各个字段
        for line in lines:
            # 唯一标识符，如 "CL:0000003"
            if line.startswith("id: "):
                term_id = line[4:].strip()
            # 术语名称，如 "native cell"
            elif line.startswith("name: "):
                name = line[6:].strip()
            # 父类关系，OBO 格式："is_a: CL:0000000 ! some comment"
            # 需要截取 "!" 之后的注释部分，只保留父类 ID
            elif line.startswith("is_a: "):
                parent_id = line[6:].strip().split("!")[0].strip()
                is_a.append(parent_id)
            # 同义词，OBO 格式："synonym: \"text\" EXACT [...]"
            # 提取引号内的文本，忽略作用域和修饰符
            elif line.startswith("synonym: "):
                match = re.search(r'"([^"]*)"', line)
                if match:
                    syn = match.group(1)
                    synonyms.append(syn)
            # 定义描述，同样提取引号内的文本
            elif line.startswith("def: "):
                match = re.search(r'"([^"]*)"', line)
                if match:
                    definition = match.group(1)

        # 只有有效的 CL 术语才被加入结果
        # 要求必须有 term_id、name，且以 "CL:" 开头
        if term_id and name and term_id.startswith("CL:"):
            terms[term_id] = {
                "name": name,
                "is_a": is_a,
                "synonyms": synonyms,
                "definition": definition,
            }
            # 构建小写同义词映射，使用启发式去重
            # 当两个术语共享同一名称时（如 "cell" 对应多个 CL ID），
            # 优先选择更具体的术语（名称更长的），因为较短的名称
            # 如 "native cell" 更可能是本体论中更通用的高层概念
            name_lower = name.lower()
            if name_lower not in synonym_map or len(name) < len(
                terms.get(synonym_map[name_lower], {}).get("name", "")
            ):
                synonym_map[name_lower] = term_id
            # 对每个同义词也应用同样的去重策略
            for syn in synonyms:
                syn_lower = syn.lower()
                if syn_lower not in synonym_map or len(syn) < len(
                    terms.get(synonym_map[syn_lower], {}).get("name", "")
                ):
                    synonym_map[syn_lower] = term_id

    return {"terms": terms, "synonym_map": synonym_map}


# ---------------------------------------------------------------------------
# 加载手动 CL ID 映射注册表
# 从 JSON 文件加载，用于处理 OBO 中尚未包含的术语或需要特定 CL ID 的术语。
# 键转换为小写以实现不区分大小写的查找。
# ---------------------------------------------------------------------------
def load_cl_id_registry(registry_path: str | Path | None = None) -> dict:
    """Load manual CL ID mappings from cl_id_registry.json.

    Returns: {lowercase_cell_type_name: "CL:xxxxxxx", ...}
    """
    if registry_path is None:
        registry_path = settings.cell_ontology_dir / "cl_id_registry.json"
    registry_path = Path(registry_path)
    if not registry_path.exists():
        return {}
    with open(registry_path) as f:
        data = json.load(f)
    # 将键归一化为小写，实现不区分大小写的查找
    return {k.lower(): v for k, v in data.get("entries", {}).items()}


# ---------------------------------------------------------------------------
# 加载手动修正数据
# 允许用户为特定术语覆盖 CL ID 或标记物类型。
# 优先级高于自动映射，用于处理自动匹配出错的情况。
# ---------------------------------------------------------------------------
def load_manual_corrections(corrections_path: str | Path | None = None) -> dict:
    """Load manual corrections from manual_corrections.json.

    Returns: {lowercase_cell_type_name: {"cl_id_override": "CL:...", "marker_overrides": {...}}, ...}
    """
    if corrections_path is None:
        corrections_path = settings.cell_ontology_dir / "manual_corrections.json"
    corrections_path = Path(corrections_path)
    if not corrections_path.exists():
        return {}
    with open(corrections_path) as f:
        data = json.load(f)
    return {k.lower(): v for k, v in data.get("entries", {}).items()}


# ---------------------------------------------------------------------------
# 归一化细胞类型名称以进行匹配
# 去除细胞类型名称中的生物学修饰词（" cell"、" cells"、"-like"、"+"等），
# 统一分隔符（空格、下划线、连字符全部统一），使得
# "T-cell"、"T cell" 和 "T_cell" 可以相互匹配。
# 注意：这不是模糊匹配，不做编辑距离或子串匹配。
# ---------------------------------------------------------------------------
def _normalize_for_matching(s: str) -> str:
    """Strip special characters and normalize for comparison."""
    s = s.lower().strip()
    # 移除生物学修饰词，这些对匹配来说是噪声
    # 例如 "T cell" → "t", "CD4+ T cell" → "cd4 t"
    for suffix in [" cell", " cells", "-like", "+"]:
        s = s.removesuffix(suffix)
    # 移除常见前缀
    for prefix in ["cd4 ", "cd8 "]:
        if s.startswith(prefix):
            s = s.removeprefix(prefix)
    # 统一所有分隔符，使 "T-cell"、"T cell" 和 "T_cell" 比较相等
    s = re.sub(r"[\s_\-]+", "", s)
    return s


# ---------------------------------------------------------------------------
# 将细胞类型名称解析为细胞本体论（CL）ID
# 匹配优先级（从高到低）：
# 1. 手动修正（用户覆盖）
# 2. 手动注册表（策展的 JSON 映射）
# 3. 精确匹配名称或同义词
# 4. 归一化匹配（去除生物学噪声后比较）
# 故意避免模糊匹配（编辑距离、子串匹配），因为它会产生太多假阳性。
# ---------------------------------------------------------------------------
def resolve_cell_type_to_cl(name: str, ontology: dict, registry: dict | None = None,
                            corrections: dict | None = None) -> str | None:
    """Try to match a cell type name to a Cell Ontology ID.

    Priority: manual corrections -> manual registry -> exact match -> normalized match.
    Fuzzy matching is deliberately avoided — it produces too many false positives.
    """
    # 空名称直接返回 None
    if not name:
        return None

    # 统一转为小写并去除首尾空格
    lookup = name.lower().strip()

    # 1. 手动修正（最高优先级）
    # 允许用户为有问题的术语覆盖任何自动映射
    if corrections and lookup in corrections:
        override = corrections[lookup].get("cl_id_override")
        if override:
            return override

    # 2. 手动注册表
    # 针对 OBO 中尚未包含或需要特定 CL ID 的术语的策展 JSON 文件
    if registry and lookup in registry:
        return registry[lookup]

    # 3. 在名称或同义词上精确匹配
    if ontology.get("synonym_map") and lookup in ontology["synonym_map"]:
        return ontology["synonym_map"][lookup]

    # 4. 归一化匹配（去除特殊字符，统一分隔符）
    # 精确匹配失败后，尝试去除生物学噪声再匹配
    # 这不是模糊匹配，不会使用编辑距离，避免将无关术语映射到同一 CL ID
    lookup_norm = _normalize_for_matching(lookup)
    for term_name, cl_id in ontology.get("synonym_map", {}).items():
        if _normalize_for_matching(term_name) == lookup_norm:
            return cl_id

    # 所有匹配策略都失败，返回 None
    return None


# ---------------------------------------------------------------------------
# 获取从 cl_id 到根节点的 is_a 父链
# 深度限制（max_depth=5）防止本体论中存在环时无限循环。
# 本体论理论上是 DAG，但损坏的文件可能引入环。
# 为简单起见，只追踪第一个父节点。
# ---------------------------------------------------------------------------
def get_parent_chain(cl_id: str, ontology: dict, max_depth: int = 5) -> list[str]:
    """Return the is_a chain from cl_id up to root."""
    chain = []
    current = cl_id
    # 深度限制防止本体论中存在环时无限循环
    for _ in range(max_depth):
        if current not in ontology.get("terms", {}):
            break
        chain.append(current)
        parents = ontology["terms"][current].get("is_a", [])
        if not parents:
            break
        current = parents[0]  # 为简单起见，只追踪第一个父节点
    return chain
