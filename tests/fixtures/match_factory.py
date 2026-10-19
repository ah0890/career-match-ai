"""Synthetic CVs and job descriptions for matching tests. All content is fictional."""

from __future__ import annotations

from config.settings import ScoringWeights
from src.cv.extraction import ExtractionResult
from src.jobs.models import JobPosting
from src.matching.engine import MatchProfile, build_profile

QUALITY_CV = """Alex Example
alex.example@example.com | +00 000 000 000 | Example City

PROFESSIONAL SUMMARY
Quality engineer with experience in manufacturing process improvement and supplier quality management.

EXPERIENCE
Senior Quality Engineer — Example Manufacturing Ltd — Jan 2019 to Present
- Led root-cause analysis using 8D methods across three production lines.
- Introduced SPC dashboards in Python and Power BI to monitor critical dimensions.
- Managed supplier PPAP submissions and incoming inspection plans.
Quality Engineer — Sample Components Co — Jun 2015 to Dec 2018
- Reduced scrap by 18% through FMEA reviews with production teams.

EDUCATION
BSc Mechanical Engineering — Example University — 2015

SKILLS
Six Sigma, ISO 9001, FMEA, SPC, Python, SQL, Minitab
"""

QUALITY_JOB = """About us
Example Devices builds fictional medical equipment.

Key responsibilities
- Lead root cause analysis and corrective actions on production lines
- Manage supplier quality and PPAP approvals
- Develop SPC dashboards to monitor critical dimensions
- Coordinate internal audits against ISO 13485

Requirements
- Bachelor's degree in Mechanical Engineering or a related field
- At least 5 years of experience in quality engineering
- Must have FMEA and SPC experience
- Proficiency in Minitab and SQL

Nice to have
- Six Sigma certification
- Experience with Tableau is a plus

Benefits
- Kubernetes training budget and a fictional gym membership
- Right to work in the UK is required
""" + "Our quality engineering team works closely with production and design engineering colleagues. " * 6

SHORT_JOB = "Quality engineer needed. Python and SQL."


def extraction(text: str) -> ExtractionResult:
    return ExtractionResult(text=text, kind="pdf", page_count=1)


def profile(text: str = QUALITY_CV) -> MatchProfile:
    return build_profile(extraction(text))


def job(description: str = QUALITY_JOB, title: str = "Senior Quality Engineer", **kw) -> JobPosting:
    base = dict(provider_id="himalayas", source_name="Himalayas", source_url="https://himalayas.app",
                title=title, company="Example Devices", listing_url="https://himalayas.app/jobs/1",
                source_job_id=title, description=description)
    base.update(kw)
    return JobPosting(**base)


DEFAULT_WEIGHTS = ScoringWeights()
