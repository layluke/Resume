#!/usr/bin/env python3
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "resume.yaml"
TEMPLATES = ROOT / "templates"
BUILD = ROOT / "build"


KNOWN_LIST_SECTIONS = (
    "skills_groups",
    "skills",
    "selected_highlights",
    "experience",
    "projects",
    "education",
    "certifications",
    "awards",
    "publications",
    "training",
    "volunteering",
)

KNOWN_MAP_SECTIONS = (
    "basics",
    "footer",
    "document",
)


def typst_escape(value: object) -> str:
    s = str(value)
    s = s.replace("\\", "\\\\")
    s = s.replace("$", "\\$")
    s = s.replace("#", "\\#")
    s = s.replace("[", "\\[")
    s = s.replace("]", "\\]")
    s = s.replace("@", "\\@")
    return s


def text_value(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, dict):
        for key in ("display", "text", "value", "name", "title"):
            candidate = value.get(key)
            if candidate not in (None, ""):
                return str(candidate)
        return ""

    return str(value)


def ensure_mapping(value: Any, path: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{path} must be a mapping/object")
    return dict(value)


def ensure_list(value: Any, path: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError(f"{path} must be a list")
    return list(value)


def ensure_list_of_mappings(value: Any, path: str) -> list[dict[str, Any]]:
    items = ensure_list(value, path)
    normalized: list[dict[str, Any]] = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise TypeError(f"{path}[{index}] must be a mapping/object")
        normalized.append(dict(item))

    return normalized


def require_non_empty_string(value: Any, path: str) -> str:
    if value is None:
        raise ValueError(f"{path} is required")
    s = str(value).strip()
    if not s:
        raise ValueError(f"{path} is required")
    return s


def _normalize_string_list(value: Any, path: str) -> list[str]:
    return [str(item) for item in ensure_list(value, path)]


def _normalize_bullets(entry: dict[str, Any], path: str) -> None:
    bullets = entry.get("bullets")
    if bullets is None:
        entry["bullets"] = []
    else:
        entry["bullets"] = _normalize_string_list(bullets, f"{path}.bullets")

    details = entry.get("details")
    if details is None:
        entry["details"] = []
    else:
        entry["details"] = _normalize_string_list(details, f"{path}.details")


def normalize_resume(raw: Any) -> dict[str, Any]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise TypeError("Top-level YAML document must be a mapping/object")

    normalized = dict(raw)
    normalized["schema_version"] = raw.get("schema_version", 1)

    for key in KNOWN_MAP_SECTIONS:
        normalized[key] = ensure_mapping(raw.get(key), key)

    normalized["summary"] = raw.get("summary", "") or ""

    for key in KNOWN_LIST_SECTIONS:
        if key == "skills":
            normalized[key] = ensure_list(raw.get(key), key)
        else:
            normalized[key] = ensure_list_of_mappings(raw.get(key), key)

    # Clearance may be either a mapping or a list. Normalize to a list for the template.
    raw_clearance = raw.get("clearance")
    if raw_clearance is None:
        normalized["clearance"] = []
    elif isinstance(raw_clearance, dict):
        normalized["clearance"] = [dict(raw_clearance)]
    else:
        normalized["clearance"] = ensure_list_of_mappings(raw_clearance, "clearance")

    basics = normalized["basics"]
    require_non_empty_string(basics.get("name"), "basics.name")

    # Support targeted schema header fields.
    if not basics.get("title") and basics.get("headline"):
        basics["title"] = basics["headline"]

    emails = basics.get("emails")
    if emails is None:
        basics["emails"] = []
    else:
        basics["emails"] = _normalize_string_list(emails, "basics.emails")

    links = basics.get("links")
    if links is None:
        basics["links"] = []
    else:
        basics["links"] = ensure_list_of_mappings(links, "basics.links")
        for index, link in enumerate(basics["links"]):
            if link.get("label") is None or link.get("url") is None:
                raise ValueError(f"basics.links[{index}] must contain label and url")

    experience = normalized["experience"]
    if not experience:
        raise ValueError("experience must contain at least one entry")

    for index, job in enumerate(experience):
        require_non_empty_string(job.get("company"), f"experience[{index}].company")

        if job.get("roles") is not None:
            roles = ensure_list_of_mappings(job.get("roles"), f"experience[{index}].roles")
            if not roles:
                raise ValueError(f"experience[{index}].roles must contain at least one entry")

            for role_index, role in enumerate(roles):
                require_non_empty_string(role.get("title"), f"experience[{index}].roles[{role_index}].title")
                _normalize_bullets(role, f"experience[{index}].roles[{role_index}]")

            job["roles"] = roles
            job["bullets"] = []
        else:
            require_non_empty_string(job.get("role"), f"experience[{index}].role")
            _normalize_bullets(job, f"experience[{index}]")
            job["roles"] = []

    for section in (
        "skills_groups",
        "selected_highlights",
        "projects",
        "education",
        "certifications",
        "awards",
        "publications",
        "clearance",
        "training",
        "volunteering",
    ):
        for index, entry in enumerate(normalized[section]):
            _normalize_bullets(entry, f"{section}[{index}]")

    # Targeted template expects these fields.
    for index, cert in enumerate(normalized["certifications"]):
        if cert.get("date") and not cert.get("issued"):
            cert["issued"] = cert["date"]
        if cert.get("year") and not cert.get("issued"):
            cert["issued"] = cert["year"]

    for index, item in enumerate(normalized["training"]):
        if item.get("year") and not item.get("completed"):
            item["completed"] = item["year"]

    for index, item in enumerate(normalized["clearance"]):
        if item.get("status") and not item.get("level") and not item.get("name"):
            item["level"] = "Clearance"

    for index, group in enumerate(normalized["skills_groups"]):
        require_non_empty_string(group.get("category"), f"skills_groups[{index}].category")
        group["items"] = _normalize_string_list(group.get("items"), f"skills_groups[{index}].items")

    normalized["skills"] = [str(item) for item in normalized["skills"]]

    footer = normalized["footer"]
    footer["note"] = footer.get(
        "note",
        "Generated from resume.yaml via Python and Typst in Forgejo Actions.",
    )

    document = normalized["document"]
    document.setdefault("show_summary", True)
    document.setdefault("show_certifications", True)
    document.setdefault("show_clearance", True)
    document.setdefault("show_training", True)

    return normalized


def main() -> None:
    BUILD.mkdir(parents=True, exist_ok=True)

    with DATA.open("r", encoding="utf-8") as f:
        raw_resume = yaml.safe_load(f)

    resume = normalize_resume(raw_resume)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["t"] = typst_escape
    env.filters["text_value"] = text_value

    git_sha = os.getenv("GIT_SHA", "dev")

    context = {
        **resume,
        "meta": {
            "git_sha": git_sha,
            "build_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "pipeline_note": resume["footer"]["note"],
        },
    }

    template = env.get_template("resume.typ.j2")
    rendered = template.render(**context)

    out = BUILD / "resume.typ"
    out.write_text(rendered, encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
