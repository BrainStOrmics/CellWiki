"""Machine-readable page extraction contract embedded in a workspace schema file."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from cellwiki.domain.contracts import ContractModel


FieldValueType = Literal["string", "integer", "boolean", "list", "mapping"]


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


class SectionContract(ContractModel):
    """Required Markdown H2 sections for one page type."""

    required: list[str] = Field(default_factory=list)


class ReferenceContract(ContractModel):
    """Reference and source-locator requirements."""

    required: bool = False
    id_fields: list[str] = Field(default_factory=lambda: ["paper_id", "source_id"])
    source_root: str = "raw"
    require_source: bool = False

    @model_validator(mode="after")
    def validate_reference_contract(self) -> "ReferenceContract":
        if (self.required or self.require_source) and not self.id_fields:
            raise ValueError("reference id_fields must not be empty when references are required")
        if not self.source_root or "/" in self.source_root or "\\" in self.source_root:
            raise ValueError("reference source_root must be one safe workspace-relative directory name")
        return self


class LinkContract(ContractModel):
    """Link-validation and target-type requirements for one page type."""

    check: bool = False
    targets: list[str] = Field(default_factory=list)


class PageContract(ContractModel):
    """One page type in the workspace extraction contract."""

    path: str
    identity: str
    frontmatter: FrontmatterContract = Field(default_factory=FrontmatterContract)
    sections: SectionContract = Field(default_factory=SectionContract)
    references: ReferenceContract = Field(default_factory=ReferenceContract)
    links: LinkContract = Field(default_factory=LinkContract)

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
        return self


class WorkspacePageSchema(ContractModel):
    """Versioned schema parsed from a workspace ``schema.md`` contract block."""

    schema_version: Literal[1]
    pages: dict[str, PageContract]

    @model_validator(mode="after")
    def validate_schema(self) -> "WorkspacePageSchema":
        if not self.pages:
            raise ValueError("pages must define at least one page type")
        path_templates = [page.path for page in self.pages.values()]
        duplicates = sorted({path for path in path_templates if path_templates.count(path) > 1})
        if duplicates:
            raise ValueError(f"duplicate page path templates: {duplicates}")
        return self


__all__ = [
    "FieldRule",
    "FrontmatterContract",
    "LinkContract",
    "PageContract",
    "ReferenceContract",
    "SectionContract",
    "WorkspacePageSchema",
]