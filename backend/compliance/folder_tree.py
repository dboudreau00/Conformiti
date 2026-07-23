"""
folder_tree.py
--------------
Builds the on-disk compliance folder tree, segregated by control.

Structure produced:

    <root>/
        SOC2/
            CC1 - Control Environment/
                CC1.1 - Integrity and ethical values/
                    _control.md         <- objective, owner, review cadence
                    policies/
                    procedures/
                    evidence/
                    forms/
                ...
        ISO27001/
        PCI-DSS-v4.0.1/

Both the Django management command and the standalone tools/generate_tree.py
call build_tree(). Folder names are filesystem-safe versions of the control
IDs and titles so the tree stays human-navigable.
"""
from __future__ import annotations

import json
import os
import re

# Standard evidence sub-folders created inside every control folder.
CONTROL_SUBFOLDERS = ["policies", "procedures", "evidence", "forms"]

# Map framework key -> top-level folder name.
FRAMEWORK_DIR = {
    "soc2": "SOC2",
    "iso27001": "ISO27001",
    "pci_dss_v4": "PCI-DSS-v4.0.1",
}

DATA_FILES = {
    "soc2": "soc2.json",
    "iso27001": "iso27001.json",
    "pci_dss_v4": "pci_dss_v4.json",
}

_SAFE = re.compile(r'[<>:"/\\|?*]+')


def safe(name: str) -> str:
    """Return a filesystem-safe folder name."""
    name = _SAFE.sub("-", name).strip().rstrip(".")
    return re.sub(r"\s+", " ", name)


def load_frameworks(data_dir: str) -> list[dict]:
    """Load every framework JSON found in data_dir."""
    frameworks = []
    for key, fname in DATA_FILES.items():
        path = os.path.join(data_dir, fname)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                frameworks.append(json.load(f))
    return frameworks


def _control_readme(fw: dict, category: dict, control: dict) -> str:
    return (
        f"# {control['control_id']} - {control['title']}\n\n"
        f"- **Framework:** {fw['name']} {fw['version']}\n"
        f"- **Category:** {category['name']}\n"
        f"- **Control ID:** {control['control_id']}\n"
        f"- **Owner:** _unassigned_\n"
        f"- **Review cadence:** annual\n"
        f"- **Next review:** _set in app_\n\n"
        f"## Objective\n{control['objective']}\n\n"
        f"## Evidence checklist\n"
        f"- [ ] Approved policy in `policies/`\n"
        f"- [ ] Documented procedure in `procedures/`\n"
        f"- [ ] Current evidence in `evidence/`\n"
        f"- [ ] Completed forms/records in `forms/`\n\n"
        f"> Objective text above is a short paraphrase, not the normative "
        f"standard text. Add licensed source text if your org holds it.\n"
    )


def build_tree(root: str, data_dir: str, write_readmes: bool = True) -> dict:
    """
    Create the folder tree under ``root`` from the framework JSON in ``data_dir``.

    Returns a summary dict: {"frameworks": n, "categories": n, "controls": n,
    "folders": n}.
    """
    frameworks = load_frameworks(data_dir)
    counts = {"frameworks": 0, "categories": 0, "controls": 0, "folders": 0}
    manifest = []

    for fw in frameworks:
        counts["frameworks"] += 1
        fw_dir = os.path.join(root, FRAMEWORK_DIR.get(fw["key"], safe(fw["name"])))
        os.makedirs(fw_dir, exist_ok=True)
        counts["folders"] += 1

        for category in fw["categories"]:
            counts["categories"] += 1
            cat_dir = os.path.join(fw_dir, safe(category["name"]))
            os.makedirs(cat_dir, exist_ok=True)
            counts["folders"] += 1

            for control in category["controls"]:
                counts["controls"] += 1
                folder_name = safe(f"{control['control_id']} - {control['title']}")
                ctrl_dir = os.path.join(cat_dir, folder_name)
                os.makedirs(ctrl_dir, exist_ok=True)
                counts["folders"] += 1

                for sub in CONTROL_SUBFOLDERS:
                    os.makedirs(os.path.join(ctrl_dir, sub), exist_ok=True)
                    counts["folders"] += 1
                    # .gitkeep so empty evidence folders survive version control
                    open(os.path.join(ctrl_dir, sub, ".gitkeep"), "a").close()

                if write_readmes:
                    with open(os.path.join(ctrl_dir, "_control.md"), "w", encoding="utf-8") as f:
                        f.write(_control_readme(fw, category, control))

                manifest.append({
                    "framework": fw["key"],
                    "category": category["key"],
                    "control_id": control["control_id"],
                    "path": os.path.relpath(ctrl_dir, root),
                })

    # top-level index + machine-readable manifest
    if write_readmes:
        with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as f:
            f.write(
                "# Compliance evidence library\n\n"
                "Folder tree segregated by framework, category and control.\n\n"
                + "".join(
                    f"- **{FRAMEWORK_DIR.get(fw['key'], fw['name'])}** - "
                    f"{fw['name']} {fw['version']} "
                    f"({sum(len(c['controls']) for c in fw['categories'])} controls)\n"
                    for fw in frameworks
                )
                + "\nEach control folder contains `policies/`, `procedures/`, "
                  "`evidence/` and `forms/` plus a `_control.md` metadata file.\n"
            )
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"counts": counts, "controls": manifest}, f, indent=2)

    return counts


if __name__ == "__main__":
    here = os.path.dirname(__file__)
    data = os.path.join(here, "data")
    out = os.path.abspath(os.path.join(here, "..", "..", "compliance-data"))
    summary = build_tree(out, data)
    print(f"Folder tree written to {out}")
    print(summary)
