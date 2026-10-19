"""Synthetic provider responses (fictional companies and jobs) for offline tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S")


def remotive_payload() -> dict:
    return {
        "0-legal-notice": "Remotive API legal notice (fixture)",
        "job-count": 5,
        "jobs": [
            {
                "id": 1001, "url": "https://remotive.com/remote-jobs/data/data-analyst-1001",
                "title": "Senior Data Analyst", "company_name": "Example Analytics Ltd",
                "category": "Data", "tags": ["python", "sql", "tableau"], "job_type": "full_time",
                "publication_date": _iso(2), "candidate_required_location": "Worldwide",
                "salary": "$80k - $95k", "description": "<p>Analyse data with <b>Python</b> and SQL.</p>"
                "<ul><li>Build dashboards</li><li>Work with stakeholders</li></ul><script>alert(1)</script>",
            },
            {
                "id": 1002, "url": "https://remotive.com/remote-jobs/software-dev/backend-1002",
                "title": "Backend Engineer", "company_name": "Sample Systems",
                "category": "Software Development", "tags": ["go", "kubernetes"], "job_type": "contract",
                "publication_date": _iso(10), "candidate_required_location": "Europe",
                "salary": "", "description": "<p>Build APIs in Go.</p>",
            },
            {
                "id": 1003, "url": "https://remotive.com/remote-jobs/data/analyst-1003",
                "title": "Data Analyst", "company_name": "Demo Retail",
                "category": "Data", "tags": [], "job_type": "",
                "publication_date": _iso(40), "candidate_required_location": "USA Only",
                "description": "<p>SQL reporting.</p>",
            },
            {"id": 1004, "title": "", "url": "https://remotive.com/x"},  # invalid: no title
            {
                "id": 1005, "url": "javascript:alert(1)", "title": "Data Quality Analyst",
                "company_name": "Unsafe Link Co", "publication_date": "not a date",
                "candidate_required_location": "Worldwide", "description": "Data checks",
            },
        ],
    }


def himalayas_payload() -> dict:
    return {"comments": "fixture", "offset": 0, "limit": 20, "totalCount": 3, "jobs": [
        {"title": "Quality Engineer", "companyName": "Example Devices", "employmentType": "Full Time",
         "minSalary": 90000, "maxSalary": 110000, "currency": "usd", "salaryPeriod": "annual",
         "seniority": ["Senior"], "locationRestrictions": [], "categories": ["Quality-Engineer"],
         "parentCategories": ["Engineering"], "pubDate": 1792198336,
         "applicationLink": "https://himalayas.app/companies/example/jobs/quality-engineer",
         "guid": "https://himalayas.app/companies/example/jobs/quality-engineer",
         "description": "<p>Lead <b>FMEA</b> and SPC.</p>"},
        {"title": "Quality Analyst", "companyName": "Sample Health", "employmentType": "Contractor",
         "minSalary": None, "maxSalary": None, "salaryPeriod": "hourly", "locationRestrictions": ["Canada"],
         "pubDate": 1792198336, "applicationLink": "https://himalayas.app/companies/sample/jobs/qa",
         "guid": "g2", "description": "Quality checks"},
        {"title": None, "companyName": "Broken"},
    ]}


def jobicy_payload() -> dict:
    return {"apiVersion": "2", "success": True, "jobCount": 2, "jobs": [
        {"id": 155742, "url": "https://jobicy.com/jobs/155742-quality-engineer", "jobTitle": "Quality Engineer",
         "companyName": "Demo Labs", "jobIndustry": ["Engineering"], "jobType": ["Full-Time"], "jobGeo": "USA",
         "jobLevel": "Senior", "jobExcerpt": "Short excerpt", "jobDescription": "<p>Own the QMS.</p>",
         "pubDate": "2026-10-18T13:48:43+00:00", "salaryMin": 120000, "salaryMax": 140000,
         "salaryCurrency": "USD", "salaryPeriod": "yearly"},
        {"id": 155743, "url": "https://jobicy.com/jobs/155743", "jobTitle": "Quality Lead",
         "companyName": "Demo EU", "jobType": ["Contract"], "jobGeo": "EMEA", "jobDescription": "",
         "jobExcerpt": "Excerpt only", "pubDate": "2026-10-17T10:00:00+00:00"},
    ]}


def remoteok_payload() -> list:
    return [
        {"last_updated": 1792346401, "legal": "API Terms of Service: Please link back (fixture)"},
        {"id": "1137542", "slug": "x", "epoch": "1792224050", "date": "2026-10-17T08:00:50+00:00",
         "company": "Curtins Example", "position": "Quality Engineer", "tags": ["quality", "engineer"],
         "location": "", "apply_url": "https://remoteok.com/remote-jobs/1137542",
         "url": "https://remoteok.com/remote-jobs/1137542", "salary_min": 0, "salary_max": 0,
         "description": "<p>Quality role</p>"},
        {"id": "1137543", "position": "Head of Technology", "company": "Other", "location": "Brazil",
         "tags": [], "url": "https://remoteok.com/remote-jobs/1137543", "salary_min": 140000, "salary_max": 0,
         "date": "2026-10-16T08:00:50+00:00", "description": "Tech leadership"},
    ]

