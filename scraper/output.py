"""Write partners.csv, jobs.csv and results.xlsx."""
from __future__ import annotations

import csv
from pathlib import Path

PARTNER_COLS = ["position", "name", "handle", "tier", "location", "team_size", "partner_since",
                "profile_url", "website", "final_url", "linkedin", "status", "careers_url",
                "discovery_method", "ats", "ats_board", "job_count", "careers_email", "used_browser", "notes"]
JOB_COLS = ["partner_name", "handle", "partner_location", "website", "careers_url", "title", "location",
            "department", "job_url", "source", "confidence"]


def rows(results: list[dict]) -> tuple[list[dict], list[dict]]:
    partners, jobs = [], []
    for r in sorted(results, key=lambda r: r["partner"].get("position", 0)):
        p = r["partner"]
        partners.append({
            **{k: p.get(k, "") for k in ("position", "name", "handle", "tier", "location", "team_size",
                                         "partner_since", "profile_url", "website", "linkedin")},
            **{k: r.get(k, "") for k in ("final_url", "status", "careers_url", "discovery_method", "ats",
                                         "ats_board", "careers_email", "used_browser", "notes")},
            "job_count": len(r.get("jobs") or []),
        })
        for j in r.get("jobs") or []:
            jobs.append({"partner_name": p.get("name", ""), "handle": p.get("handle", ""),
                         "partner_location": p.get("location", ""), "website": p.get("website", ""),
                         "careers_url": r.get("careers_url", ""), "title": j["title"],
                         "location": j.get("location", ""), "department": j.get("department", ""),
                         "job_url": j.get("url", ""), "source": j.get("source", ""),
                         "confidence": j.get("confidence", "")})
    return partners, jobs


def write_all(results: list[dict], out: Path) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    partners, jobs = rows(results)
    paths = {"partners": out / "partners.csv", "jobs": out / "jobs.csv", "xlsx": out / "results.xlsx"}
    for path, cols, data in ((paths["partners"], PARTNER_COLS, partners), (paths["jobs"], JOB_COLS, jobs)):
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel reads UTF-8
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(data)
    try:
        from openpyxl import Workbook
        from openpyxl.utils import get_column_letter
        wb = Workbook()
        for i, (name, cols, data) in enumerate((("Jobs", JOB_COLS, jobs), ("Partners", PARTNER_COLS, partners))):
            ws = wb.active if i == 0 else wb.create_sheet()
            ws.title = name
            ws.append(cols)
            for row in data:
                ws.append([row.get(c, "") for c in cols])
            ws.freeze_panes = "A2"
            ws.auto_filter.ref = ws.dimensions
            for ci, c in enumerate(cols, 1):
                ws.column_dimensions[get_column_letter(ci)].width = min(60, max(10, len(c) + 4))
        wb.save(paths["xlsx"])
    except ImportError:
        paths.pop("xlsx")
    return paths
