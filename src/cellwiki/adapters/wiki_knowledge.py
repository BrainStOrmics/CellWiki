# =============================================================================
# 知识库构建 —— 将多篇论文的 LLM 提取结果合并为统一的细胞类型 Wiki
# =============================================================================
# 核心流程：加载所有提取结果 → 合并（并集策略，永不删除）→ CL ID 去重 →
# 生成 Wiki 页面。支持多源标记物合并、证据冲突检测、上下文聚合等功能。
# v2.0 扩展支持多实体合并（细胞类型、标记基因、组织、疾病等）。
# =============================================================================

"""Knowledge base construction: merge LLM extractions from multiple papers into a unified cell-type wiki, then regenerate wiki pages."""

import json
import logging
from cellwiki.config import settings
from cellwiki.models import ExtractionResult, WikiCellType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 保存提取结果到 JSON 文件
# 使用 paper_id 作为文件名，确保每个论文的提取结果可以独立存储和加载。
# ---------------------------------------------------------------------------
def save_extraction(result: ExtractionResult) -> str:
    """Save an ExtractionResult as JSON to the extraction directory.

    Returns the paper_id used for the saved file.
    """
    # 确保提取目录存在，如果不存在则创建
    settings.extraction_dir.mkdir(parents=True, exist_ok=True)
    paper_id = result.paper.paper_id
    # 以 paper_id 为文件名保存 JSON
    dest = settings.extraction_dir / f"{paper_id}.json"

    with open(dest, "w", encoding="utf-8") as f:
        # 将 Pydantic 模型转换为可序列化的字典
        data = result.model_dump(mode="json")
        json.dump(data, f, indent=2, ensure_ascii=False)

    return paper_id


# ---------------------------------------------------------------------------
# 加载所有已保存的提取结果
# 按文件名排序后加载，确保每次加载的顺序一致。
# ---------------------------------------------------------------------------
def load_all_extractions() -> list[ExtractionResult]:
    """Load all saved extraction files from the extraction directory."""
    results = []
    # 按文件名排序以确保加载顺序一致
    for f in sorted(settings.extraction_dir.glob("*.json")):
        with open(f) as fh:
            data = json.load(fh)
        # 反序列化为 Pydantic 模型，自动进行类型验证
        results.append(ExtractionResult(**data))
    return results


# ---------------------------------------------------------------------------
# 将所有提取结果合并为 WikiCellType 字典
# 合并策略：并集（永不删除）。多篇论文对同一细胞类型的标记物、
# 功能和引用进行累积贡献。
# 关键特性：
# - 以 standard_name 为合并键
# - 自动检测标记物冲突（同一基因在不同论文中标记为不同类型）
# - 保留更长的描述文本
# - 去重引用和来源
# ---------------------------------------------------------------------------
def merge_to_wiki(extractions: list[ExtractionResult]) -> dict[str, WikiCellType]:
    """Merge all extraction results into a dictionary of WikiCellType.

    Strategy: union (never delete). Multiple papers contribute markers,
    functions, and references to the same cell type.
    """
    wiki: dict[str, WikiCellType] = {}

    # 遍历所有提取结果
    for extraction in extractions:
        # 遍历每篇论文中提取的每个细胞类型
        for ct in extraction.cell_types:
            # 跳过没有标准名称的条目，它们不能作为合并键
            if not ct.standard_name:
                continue

            key = ct.standard_name
            # 如果该细胞类型尚未在 wiki 中，创建新条目
            if key not in wiki:
                # 延迟导入避免循环依赖
                from cellwiki.adapters.markdown_renderer import _proper_title_case
                display = _proper_title_case(key)
                wiki[key] = WikiCellType(
                    standard_name=key,
                    display_name=display,
                    cl_id=ct.cl_id,
                    description=ct.description,
                    parent_type=ct.parent_type,
                )

            wiki_type = wiki[key]

            # ---- 合并别名 ----
            # 添加原始名称和同义词作为别名，方便搜索时发现
            wiki_type.aliases.add(ct.name)
            wiki_type.aliases.update(ct.synonyms)

            # ---- 合并 CL ID ----
            # 如果当前没有 CL ID 但新提取有，则使用新提取的
            if ct.cl_id and not wiki_type.cl_id:
                wiki_type.cl_id = ct.cl_id

            # ---- 合并父类型 ----
            # 如果当前没有父类型但新提取有，则使用新提取的
            if ct.parent_type and not wiki_type.parent_type:
                wiki_type.parent_type = ct.parent_type

            # ---- 合并描述（保留更长的）----
            if len(ct.description) > len(wiki_type.description):
                wiki_type.description = ct.description

            # ---- 合并标记物（以基因符号为键）----
            for marker in ct.markers:
                entry = {
                    "marker_type": marker.marker_type.value,
                    "evidence": marker.evidence,
                    "strength": marker.strength,
                    "paper_id": ct.paper_ref.paper_id,
                }
                # 如果该基因尚未有标记物记录，初始化列表
                if marker.gene_symbol not in wiki_type.markers:
                    wiki_type.markers[marker.gene_symbol] = []
                # 避免同一来源的完全重复记录，但保留跨来源或跨类型的证据。
                duplicate = any(
                    existing["paper_id"] == entry["paper_id"]
                    and existing["marker_type"] == entry["marker_type"]
                    and existing["evidence"] == entry["evidence"]
                    for existing in wiki_type.markers[marker.gene_symbol]
                )
                if not duplicate:
                    # 检测冲突：同一基因在不同论文中有不同的标记物类型
                    existing_types = {
                        e["marker_type"] for e in wiki_type.markers[marker.gene_symbol]
                    }
                    if existing_types and marker.marker_type.value not in existing_types:
                        entry["conflict"] = True
                        marker_type_order = {"positive": 0, "negative": 1, "transcript": 2}
                        conflict_types = sorted(
                            existing_types | {marker.marker_type.value},
                            key=lambda value: (marker_type_order.get(value, 99), value),
                        )
                        conflict = f"{marker.gene_symbol}: {' vs '.join(conflict_types)}"
                        if conflict not in wiki_type.conflicts:
                            wiki_type.conflicts.append(conflict)
                        logger.info(
                            f"Marker conflict for {marker.gene_symbol} in {key}: "
                            f"{existing_types} vs {marker.marker_type.value}"
                        )
                    wiki_type.markers[marker.gene_symbol].append(entry)

            # ---- 合并功能（以描述文本为键）----
            for func in ct.functions:
                entry = {
                    "pathway": func.pathway,
                    "evidence": func.evidence,
                    "paper_id": ct.paper_ref.paper_id,
                }
                if func.description not in wiki_type.functions:
                    wiki_type.functions[func.description] = []
                if not any(e["evidence"] == func.evidence for e in wiki_type.functions[func.description]):
                    wiki_type.functions[func.description].append(entry)

            # ---- 合并上下文（按物种分组）----
            for species in ct.species:
                if species not in wiki_type.contexts:
                    wiki_type.contexts[species] = {"tissues": [], "diseases": []}
                for t in ct.tissues:
                    if t not in wiki_type.contexts[species]["tissues"]:
                        wiki_type.contexts[species]["tissues"].append(t)
                for d in ct.diseases:
                    if d not in wiki_type.contexts[species]["diseases"]:
                        wiki_type.contexts[species]["diseases"].append(d)

            # ---- 合并子群 ----
            wiki_type.subpopulations.update(ct.subpopulations)

            # ---- 合并引用（按 paper_id 去重）----
            ref_entry = {
                "paper_id": ct.paper_ref.paper_id,
                "title": ct.paper_ref.title,
                "doi": ct.paper_ref.doi,
                "year": ct.paper_ref.year,
            }
            if not any(r["paper_id"] == ref_entry["paper_id"] for r in wiki_type.references):
                wiki_type.references.append(ref_entry)

            # ---- 追踪来源（按 paper_id 去重）----
            if ct.paper_ref.paper_id not in wiki_type.sources:
                wiki_type.sources.append(ct.paper_ref.paper_id)

    return wiki


# ---------------------------------------------------------------------------
# 将 source 合并到 target（并集策略）
# 被 deduplicate_by_cl_id 用于合并具有相同 CL ID 的条目。
# 合并时保留所有唯一值，不删除任何已有数据。
# ---------------------------------------------------------------------------
def _merge_wiki_type(target: WikiCellType, source: WikiCellType):
    """Merge source into target (union strategy). Used by deduplicate_by_cl_id to collapse entries."""
    target.aliases.update(source.aliases)
    if source.cl_id and not target.cl_id:
        target.cl_id = source.cl_id
    if source.parent_type and not target.parent_type:
        target.parent_type = source.parent_type
    if len(source.description) > len(target.description):
        target.description = source.description

    for gene, entries in source.markers.items():
        if gene not in target.markers:
            target.markers[gene] = []
        for entry in entries:
            if not any(e["paper_id"] == entry["paper_id"] and e["evidence"] == entry["evidence"]
                       for e in target.markers[gene]):
                target.markers[gene].append(entry)

    for desc, entries in source.functions.items():
        if desc not in target.functions:
            target.functions[desc] = []
        for entry in entries:
            if not any(e["paper_id"] == entry["paper_id"] and e["evidence"] == entry["evidence"]
                       for e in target.functions[desc]):
                target.functions[desc].append(entry)

    for species, info in source.contexts.items():
        if species not in target.contexts:
            target.contexts[species] = {"tissues": [], "diseases": []}
        for t in info["tissues"]:
            if t not in target.contexts[species]["tissues"]:
                target.contexts[species]["tissues"].append(t)
        for d in info["diseases"]:
            if d not in target.contexts[species]["diseases"]:
                target.contexts[species]["diseases"].append(d)

    target.subpopulations.update(source.subpopulations)
    for ref in source.references:
        if not any(r["paper_id"] == ref["paper_id"] for r in target.references):
            target.references.append(ref)
    for s in source.sources:
        if s not in target.sources:
            target.sources.append(s)


# ---------------------------------------------------------------------------
# 按 CL ID 去重合并 wiki 条目
# 当多个条目具有相同的有效 CL ID 时，将它们合并为一个。
# CL:0000000 是根术语，不用于去重。
# 保留第一个条目作为规范版本，将其他条目合并到其中。
# ---------------------------------------------------------------------------
def deduplicate_by_cl_id(wiki: dict[str, WikiCellType]) -> dict[str, WikiCellType]:
    """Merge wiki entries that share the same valid CL ID.

    CL:0000000 is the root term and not useful for deduplication.
    Keeps the first entry as canonical, merges others into it.
    """
    # 按 CL ID 分组：cl_id -> [key1, key2, ...]
    cl_groups: dict[str, list[str]] = {}
    # 没有 CL ID 的条目单独处理
    no_cl: list[str] = []

    for key, wt in wiki.items():
        if wt.cl_id and wt.cl_id != "CL:0000000":
            cl_groups.setdefault(wt.cl_id, []).append(key)
        else:
            no_cl.append(key)

    merged_keys = set()
    for cl_id, keys in cl_groups.items():
        # 如果只有一个条目，不需要合并
        if len(keys) < 2:
            merged_keys.update(keys)
            continue

        # 保留第一个作为规范版本，将其他条目合并到其中
        canonical = keys[0]
        merged_keys.add(canonical)
        for k in keys[1:]:
            _merge_wiki_type(wiki[canonical], wiki[k])
            # 将合并条目的名称添加为别名，确保通过搜索仍可找到
            wiki[canonical].aliases.add(wiki[k].display_name or k)
            wiki[canonical].aliases.add(k)

    # 重建 wiki 字典，只包含合并后的键 + 无 CL ID 的条目
    result = {k: wiki[k] for k in merged_keys if k in wiki}
    result.update({k: wiki[k] for k in no_cl if k not in result})

    # 输出去重统计信息
    n_removed = len(wiki) - len(result)
    if n_removed > 0:
        print(f"  Deduplicated: {len(wiki)} -> {len(result)} pages (removed {n_removed} duplicates)")

    return result


# ---------------------------------------------------------------------------
# 完整 Wiki 重建流程
# 1. 加载所有提取结果
# 2. 合并为 WikiCellType 字典
# 3. 从本体论解析 CL ID
# 4. 按 CL ID 去重
# 5. 删除过时的页面
# 6. 生成细胞类型页面
# 7. 生成索引页面
# ---------------------------------------------------------------------------
def rebuild_wiki():
    """Full wiki rebuild: load all extractions, merge, deduplicate, regenerate pages."""
    extractions = load_all_extractions()
    if not extractions:
        print("No extractions found. Add papers first.")
        return

    wiki = merge_to_wiki(extractions)

    # 从细胞本体论解析 CL ID
    from cellwiki.ontology import load_cell_ontology, resolve_cell_type_to_cl, load_cl_id_registry, load_manual_corrections
    ontology = load_cell_ontology()
    registry = load_cl_id_registry()
    corrections = load_manual_corrections()

    # 对每个没有 CL ID 的条目尝试解析
    for key, wt in wiki.items():
        if not wt.cl_id:
            # 首先尝试用 display_name 解析，如果失败则回退到原始键名
            wt.cl_id = resolve_cell_type_to_cl(wt.display_name or key, ontology, registry, corrections)
            if not wt.cl_id:
                wt.cl_id = resolve_cell_type_to_cl(key, ontology, registry, corrections)

    # 按 CL ID 去重
    wiki = deduplicate_by_cl_id(wiki)

    # 生成 Wiki 页面
    from cellwiki.adapters.markdown_renderer import generate_cell_type_page, generate_index_page

    settings.wiki_cell_types_dir.mkdir(parents=True, exist_ok=True)

    # 删除过时的页面（不再存在于 wiki 中的键）
    valid_keys = set(wiki.keys())
    for existing in settings.wiki_cell_types_dir.glob("*.md"):
        if existing.stem not in valid_keys:
            existing.unlink()

    # 为每个细胞类型生成页面
    for key, wt in wiki.items():
        generate_cell_type_page(key, wt)

    # 生成索引页面
    generate_index_page(wiki)

    print(f"Generated {len(wiki)} cell type pages.")


# ============================================================
# CellWiki v2.0 — Multi-Omics Knowledge Merger
# CellWiki v2.0 多组学知识合并器
# 扩展支持多种实体类型（细胞类型、标记基因、组织、疾病等）的合并。
# ============================================================


class MultiOmicsMerger:
    """Merge multi-entity extractions into a unified WikiState.

    将多实体提取结果合并为统一的 WikiState，支持细胞类型、标记基因、
    组织、疾病、方法和轨迹等多种实体类型的独立合并。
    """

    def __init__(self):
        # 初始化各类实体的存储字典
        self.cell_types: dict = {}
        self.marker_genes: dict = {}
        self.tissues: dict = {}
        self.diseases: dict = {}
        self.methods: dict = {}
        self.trajectories: dict = {}

    # ---- 合并细胞类型 ----
    # 复用已有的 merge_to_wiki 逻辑
    def merge_cell_types(self, extractions: list) -> dict:
        """Merge cell type extractions (reuses existing merge_to_wiki logic)."""
        # 延迟导入避免循环依赖
        from cellwiki.adapters.wiki_knowledge import merge_to_wiki

        wiki = merge_to_wiki(extractions)
        # 将 WikiCellType 对象转换为纯字典格式
        self.cell_types = {
            key: {
                "standard_name": wt.standard_name,
                "display_name": wt.display_name,
                "cl_id": wt.cl_id,
                "parent_type": wt.parent_type,
                "description": wt.description,
                "markers": wt.markers,
                "functions": wt.functions,
                "subpopulations": list(wt.subpopulations),
                "references": wt.references,
                "sources": wt.sources,
                "identity": wt.identity,
                "state": wt.state,
                "context": wt.context,
            }
            for key, wt in wiki.items()
        }
        return self.cell_types

    # ---- 合并标记基因 ----
    # 跨论文提取标记基因信息，统计每个基因出现在哪些细胞类型中
    def merge_marker_genes(self, extractions: list) -> dict:
        """Extract and merge marker gene information across papers."""
        for extraction in extractions:
            for ct in extraction.cell_types:
                for marker in ct.markers:
                    gene = marker.gene_symbol
                    # 如果该基因尚未记录，初始化条目
                    if gene not in self.marker_genes:
                        self.marker_genes[gene] = {
                            "gene_symbol": gene,
                            "cell_types_expressed": [],
                            "source_count": 0,
                            "sources": [],
                            # 默认为最低证据等级，由 assign_evidence_tiers() 升级
                            "evidence_tier": 5,
                        }

                    mg = self.marker_genes[gene]
                    ct_name = ct.standard_name
                    if ct_name not in mg["cell_types_expressed"]:
                        mg["cell_types_expressed"].append(ct_name)

                    paper_id = extraction.paper.paper_id if extraction.paper else "unknown"
                    if paper_id not in mg["sources"]:
                        mg["sources"].append(paper_id)
                        mg["source_count"] += 1

        return self.marker_genes

    # ---- 合并组织信息 ----
    # 汇总每个组织中发现的细胞类型
    def merge_tissues(self, extractions: list) -> dict:
        """Extract and merge tissue information."""
        for extraction in extractions:
            for ct in extraction.cell_types:
                for tissue in ct.tissues:
                    # 归一化为小写蛇形命名，用作稳定的字典键
                    tissue_key = tissue.lower().replace(" ", "_")
                    if tissue_key not in self.tissues:
                        self.tissues[tissue_key] = {
                            "name": tissue_key,
                            "display_name": tissue,
                            "cell_types_found": {},
                            "source_count": 0,
                            "sources": [],
                        }

                    t = self.tissues[tissue_key]
                    ct_name = ct.standard_name
                    if ct_name not in t["cell_types_found"]:
                        t["cell_types_found"][ct_name] = "present"

                    paper_id = extraction.paper.paper_id if extraction.paper else "unknown"
                    if paper_id not in t["sources"]:
                        t["sources"].append(paper_id)
                        t["source_count"] += 1

        return self.tissues

    # ---- 合并疾病关联 ----
    # 汇总每种疾病相关的细胞类型
    def merge_diseases(self, extractions: list) -> dict:
        """Extract and merge disease associations."""
        for extraction in extractions:
            for ct in extraction.cell_types:
                for disease in ct.diseases:
                    # 归一化为小写蛇形命名，用作稳定的字典键
                    disease_key = disease.lower().replace(" ", "_")
                    if disease_key not in self.diseases:
                        self.diseases[disease_key] = {
                            "name": disease_key,
                            "display_name": disease,
                            "associated_cell_types": {},
                            "source_count": 0,
                            "sources": [],
                        }

                    d = self.diseases[disease_key]
                    ct_name = ct.standard_name
                    if ct_name not in d["associated_cell_types"]:
                        d["associated_cell_types"][ct_name] = "associated"

                    paper_id = extraction.paper.paper_id if extraction.paper else "unknown"
                    if paper_id not in d["sources"]:
                        d["sources"].append(paper_id)
                        d["source_count"] += 1

        return self.diseases

    # ---- 检测冲突 ----
    # 目前为占位方法，需要完整的提取数据才能实现
    def detect_conflicts(self) -> list:
        """Detect conflicts across merged data."""
        conflicts = []

        # 标记物冲突：同一基因在同一细胞类型中有不同的标记物类型
        for gene, mg in self.marker_genes.items():
            for extraction in [None]:  # 占位 - 需要完整的提取数据
                pass

        return conflicts

    # ---- 分配证据等级 ----
    # 根据来源论文数量自动分配证据等级
    # Tier 3 = 3+ 篇论文（强证据）
    # Tier 4 = 1-2 篇论文（中等证据）
    # Tier 5 = 无支持（未验证）
    def assign_evidence_tiers(self):
        """Assign evidence tiers based on source counts.

        Tier 3 = 3+ papers (strong), Tier 4 = 1-2 papers (moderate), Tier 5 = unsupported.
        """
        for gene, mg in self.marker_genes.items():
            count = mg.get("source_count", 0)
            if count >= 3:
                mg["evidence_tier"] = 3
            elif count >= 1:
                mg["evidence_tier"] = 4
            else:
                mg["evidence_tier"] = 5

    # ---- 获取完整 WikiState ----
    def get_wiki_state(self) -> dict:
        """Return the complete WikiState."""
        return {
            "cell_types": self.cell_types,
            "marker_genes": self.marker_genes,
            "tissues": self.tissues,
            "diseases": self.diseases,
            "methods": self.methods,
            "trajectories": self.trajectories,
        }
