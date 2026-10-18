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
