"""Machine-readable page extraction contract embedded in a workspace schema file."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from cellwiki.domain.contracts import ContractModel


FieldValueType = Literal["string", "integer", "boolean", "list", "mapping"]
BlockType = Literal["paragraphs", "bullets", "table", "mixed"]
CitationPolicy = Literal["optional", "required", "per-item"]
SourcePolicy = Literal["none", "raw"]
ChildrenPolicy = Literal["none", "allowed"]


class FieldRule(ContractModel):
    """One supported frontmatter value rule."""

    type: FieldValueType
    const: Any = None
    enum: list[Any] | None = None
    pattern: str | None = None
    nullable: bool = False
    min_length: int | None = Field(default=None, ge=0)

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            re.compile(value)
        except re.error as error:
            raise ValueError(f"invalid pattern: {error}") from error
        return value


class FrontmatterContract(ContractModel):
    """Required and optional frontmatter fields for one page type."""

    required: dict[str, FieldRule] = Field(default_factory=dict)
    optional: dict[str, FieldRule] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_duplicate_fields(self) -> "FrontmatterContract":
        overlap = sorted(set(self.required) & set(self.optional))
        if overlap:
            raise ValueError(f"frontmatter fields cannot be both required and optional: {overlap}")
        return self


class NumberRule(ContractModel):
    """Numeric bounds for one table cell."""

    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> "NumberRule":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("number rule min must not exceed max")
        return self


class ColumnRule(ContractModel):
    """One table column rule used by template lint."""

    enum: list[str] | None = None
    wikilink: str | None = None
    number: NumberRule | None = None
    allow_unknown: bool = False
    source: bool = False
    evidence: bool = False

    @model_validator(mode="after")
    def reject_ambiguous_rule(self) -> "ColumnRule":
        selected = sum(
            value is not None and value is not False
            for value in (self.enum, self.wikilink, self.number, self.source, self.evidence)
        )
        if selected > 1:
            raise ValueError("a column rule must select exactly one rule kind")
        return self


class ItemRule(ContractModel):
    """Rule applied to one bullet or numbered list item."""

    wikilink: str | None = None
    allow_prefixes: list[str] = Field(default_factory=list)


class LineRule(ContractModel):
    """Rule applied to one labelled line inside a free-form section."""

    label: str
    wikilink: str | None = None
    separator: str = ","
    evidence_line: bool = False
    source_line: bool = False

    @model_validator(mode="after")
    def reject_ambiguous_line_rule(self) -> "LineRule":
        selected = sum(
            value is not None and value is not False
            for value in (self.wikilink, self.evidence_line, self.source_line)
        )
        if selected > 1:
            raise ValueError("a line rule must select exactly one rule kind")
        return self


class SectionRule(ContractModel):
    """One H2 section contract in a page template."""

    name: str
    required: bool = False
    block: BlockType = "mixed"
    min: int = Field(default=0, ge=0)
    columns: list[str] = Field(default_factory=list)
    column_rules: dict[str, ColumnRule] = Field(default_factory=dict)
    citation: CitationPolicy = "optional"
    source: SourcePolicy = "none"
    item_rules: list[ItemRule] = Field(default_factory=list)
    line_rules: list[LineRule] = Field(default_factory=list)
    children: ChildrenPolicy = "none"
    evidence_items: bool = False

    @model_validator(mode="after")
    def validate_section_rule(self) -> "SectionRule":
        if self.block == "table" and not self.columns:
            raise ValueError("table sections must declare columns")
        unknown_rules = sorted(set(self.column_rules) - set(self.columns))
        if unknown_rules:
            raise ValueError(f"column_rules reference unknown columns: {unknown_rules}")
        if self.block != "table" and self.column_rules:
            raise ValueError("column_rules are only valid for table sections")
        if self.item_rules and self.block != "bullets":
            raise ValueError("item_rules are only valid for bullet sections")
        return self


class PageTemplate(ContractModel):
    """Markdown body template compiled from one ``cellwiki-template`` block."""

    page_type: str
    title_field: str
    required_any: list[str] = Field(default_factory=list)
    sections: list[SectionRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_template(self) -> "PageTemplate":
        names = [section.name for section in self.sections]
        if not names:
            raise ValueError("template must declare at least one H2 section")
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate template sections: {duplicates}")
        unknown_any = sorted(set(self.required_any) - set(names))
        if unknown_any:
            raise ValueError(f"required_any references unknown sections: {unknown_any}")
        return self

    def section(self, name: str) -> SectionRule | None:
        for section in self.sections:
            if section.name == name:
                return section
        return None


class PageContract(ContractModel):
    """One page type in the workspace extraction contract."""

    path: str
    identity: str
    source_field: str
    source_id_field: str | None = None
    frontmatter: FrontmatterContract = Field(default_factory=FrontmatterContract)
    template: PageTemplate | None = None

    @model_validator(mode="after")
    def validate_page_contract(self) -> "PageContract":
        if not self.path.startswith("wiki/"):
            raise ValueError("page path must start with wiki/")
        if self.path.count("{id}") != 1:
            raise ValueError("page path must contain exactly one {id} placeholder")
        if not self.path.endswith(".md"):
            raise ValueError("page path must end with .md")
        if self.identity not in self.frontmatter.required:
            raise ValueError("identity field must be a required frontmatter field")
        identity_rule = self.frontmatter.required[self.identity]
        if identity_rule.type != "string":
            raise ValueError("identity field must use type: string")
        if self.source_field not in self.frontmatter.required:
            raise ValueError("source_field must be a required frontmatter field")
        source_rule = self.frontmatter.required[self.source_field]
        if source_rule.type != "list":
            raise ValueError("source_field must use type: list")
        if self.source_id_field is not None and not self.source_id_field:
            raise ValueError("source_id_field must not be empty when provided")
        return self


class WorkspacePageSchema(ContractModel):
    """Versioned schema parsed from a workspace ``schema.md`` contract block."""

    schema_version: Literal[2]
    pages: dict[str, PageContract]

    @model_validator(mode="after")
    def validate_schema(self) -> "WorkspacePageSchema":
        if not self.pages:
            raise ValueError("pages must define at least one page type")
        path_templates = [page.path for page in self.pages.values()]
        duplicates = sorted({path for path in path_templates if path_templates.count(path) > 1})
        if duplicates:
            raise ValueError(f"duplicate page path templates: {duplicates}")
        missing_templates = sorted(name for name, page in self.pages.items() if page.template is None)
        if missing_templates:
            raise ValueError(f"page types missing markdown templates: {missing_templates}")
        template_types = [page.template.page_type for page in self.pages.values() if page.template]
        if len(template_types) != len(set(template_types)):
            raise ValueError("each page type must have exactly one markdown template")
        for page_type, page in self.pages.items():
            if page.template is not None and page.template.page_type != page_type:
                raise ValueError(
                    f"template page_type {page.template.page_type!r} does not match {page_type!r}"
                )
        return self


__all__ = [
    "BlockType",
    "ChildrenPolicy",
    "CitationPolicy",
    "ColumnRule",
    "FieldRule",
    "FrontmatterContract",
    "ItemRule",
    "LineRule",
    "NumberRule",
    "PageContract",
    "PageTemplate",
    "SectionRule",
    "SourcePolicy",
    "WorkspacePageSchema",
]
