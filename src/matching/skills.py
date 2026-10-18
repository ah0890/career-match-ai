"""Skill taxonomy and dictionary-based skill extraction.

Each canonical skill has aliases. Matching is case-insensitive and respects word
boundaries, so "R" never matches inside "React", and "Java" never matches "JavaScript".
The taxonomy is deliberately broad (technical, engineering, quality, business and soft
skills) and can be extended without code changes elsewhere.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

Category = Literal["technical", "tool", "methodology", "domain", "soft", "language"]


@dataclass(frozen=True)
class SkillDef:
    name: str
    category: Category
    aliases: tuple[str, ...] = ()


def _s(name: str, category: Category, *aliases: str) -> SkillDef:
    return SkillDef(name, category, aliases)


TAXONOMY: tuple[SkillDef, ...] = (
    # Programming & data
    _s("Python", "technical"), _s("Java", "technical"), _s("JavaScript", "technical", "JS", "ECMAScript"),
    _s("TypeScript", "technical"), _s("C#", "technical", "C Sharp"), _s("C++", "technical", "CPP"),
    _s("C", "technical"), _s("Go", "technical", "Golang"), _s("Rust", "technical"), _s("PHP", "technical"),
    _s("Ruby", "technical"), _s("Kotlin", "technical"), _s("Swift", "technical"), _s("R", "technical"),
    _s("MATLAB", "technical"), _s("SQL", "technical"), _s("NoSQL", "technical"), _s("HTML", "technical", "HTML5"),
    _s("CSS", "technical", "CSS3"), _s("Bash", "technical", "Shell scripting"), _s("VBA", "technical"),
    _s("React", "technical", "React.js", "ReactJS"), _s("Angular", "technical"), _s("Vue.js", "technical", "Vue"),
    _s("Node.js", "technical", "NodeJS"), _s("Django", "technical"), _s("Flask", "technical"),
    _s("FastAPI", "technical"), _s("Spring", "technical", "Spring Boot"), _s(".NET", "technical", "dotnet", "ASP.NET"),
    _s("REST APIs", "technical", "REST", "RESTful", "REST API"), _s("GraphQL", "technical"),
    _s("Machine Learning", "technical", "ML"), _s("Deep Learning", "technical"),
    _s("Natural Language Processing", "technical", "NLP"), _s("Computer Vision", "technical"),
    _s("Data Analysis", "technical", "Data Analytics"), _s("Data Visualization", "technical", "Data Visualisation"),
    _s("Statistics", "technical", "Statistical Analysis"), _s("ETL", "technical"),
    _s("Data Engineering", "technical"), _s("Data Modeling", "technical", "Data Modelling"),
    _s("Pandas", "tool"), _s("NumPy", "tool"), _s("scikit-learn", "tool", "sklearn"),
    _s("TensorFlow", "tool"), _s("PyTorch", "tool"), _s("Spark", "tool", "Apache Spark", "PySpark"),
    _s("Hadoop", "tool"), _s("Airflow", "tool", "Apache Airflow"), _s("Kafka", "tool", "Apache Kafka"),
    _s("Power BI", "tool", "PowerBI"), _s("Tableau", "tool"), _s("Looker", "tool"), _s("Excel", "tool", "MS Excel", "Microsoft Excel"),
    _s("PostgreSQL", "tool", "Postgres"), _s("MySQL", "tool"), _s("SQL Server", "tool", "MSSQL"),
    _s("Oracle Database", "tool", "Oracle DB"), _s("MongoDB", "tool"), _s("Redis", "tool"), _s("Snowflake", "tool"),
    _s("BigQuery", "tool"), _s("Databricks", "tool"),
    # Cloud & DevOps
    _s("AWS", "tool", "Amazon Web Services"), _s("Azure", "tool", "Microsoft Azure"),
    _s("Google Cloud", "tool", "GCP", "Google Cloud Platform"), _s("Docker", "tool"), _s("Kubernetes", "tool", "K8s"),
    _s("Terraform", "tool"), _s("Ansible", "tool"), _s("Jenkins", "tool"), _s("GitHub Actions", "tool"),
    _s("CI/CD", "methodology", "Continuous Integration", "Continuous Delivery"), _s("Git", "tool"),
    _s("Linux", "tool"), _s("DevOps", "methodology"), _s("Microservices", "technical"),
    _s("Cybersecurity", "domain", "Information Security", "InfoSec"), _s("Networking", "technical", "TCP/IP"),
    # Software practice
    _s("Agile", "methodology"), _s("Scrum", "methodology"), _s("Kanban", "methodology"),
    _s("Test Automation", "technical", "Automated Testing"), _s("Selenium", "tool"), _s("Unit Testing", "technical"),
    _s("Jira", "tool"), _s("Confluence", "tool"),
    # Engineering, manufacturing & quality
    _s("AutoCAD", "tool"), _s("SolidWorks", "tool"), _s("CATIA", "tool"), _s("Creo", "tool"),
    _s("ANSYS", "tool"), _s("Finite Element Analysis", "technical", "FEA"), _s("CAD", "tool"),
    _s("GD&T", "technical", "Geometric Dimensioning and Tolerancing"), _s("PLC Programming", "technical", "PLC"),
    _s("SCADA", "tool"), _s("Lean Manufacturing", "methodology", "Lean"), _s("Six Sigma", "methodology"),
    _s("Kaizen", "methodology"), _s("5S", "methodology"), _s("Root Cause Analysis", "methodology", "RCA", "Root-cause analysis"),
    _s("8D", "methodology", "8D Problem Solving"), _s("FMEA", "methodology", "PFMEA", "DFMEA"),
    _s("Statistical Process Control", "methodology", "SPC"), _s("PPAP", "methodology"), _s("APQP", "methodology"),
    _s("Measurement System Analysis", "methodology", "MSA", "Gauge R&R"), _s("Minitab", "tool"),
    _s("ISO 9001", "domain"), _s("ISO 14001", "domain"), _s("ISO 45001", "domain"), _s("IATF 16949", "domain"),
    _s("ISO 13485", "domain"), _s("GMP", "domain", "Good Manufacturing Practice"), _s("HACCP", "domain"),
    _s("Quality Management Systems", "domain", "QMS"), _s("Internal Auditing", "methodology", "Internal Audit"),
    _s("Supplier Quality", "domain", "Supplier Quality Management"), _s("CAPA", "methodology"),
    _s("Process Improvement", "methodology", "Continuous Improvement"), _s("HSE", "domain", "EHS", "Health and Safety"),
    _s("Preventive Maintenance", "domain"), _s("Electrical Engineering", "domain"),
    _s("Mechanical Engineering", "domain"), _s("Civil Engineering", "domain"),
    _s("Primavera P6", "tool", "Primavera"), _s("SAP", "tool"), _s("ERP", "tool"),
    # Business & management
    _s("Project Management", "methodology"), _s("Program Management", "methodology", "Programme Management"),
    _s("Product Management", "methodology"), _s("Stakeholder Management", "methodology"),
    _s("Risk Management", "methodology"), _s("Change Management", "methodology"),
    _s("Budgeting", "domain", "Budget Management"), _s("Financial Analysis", "domain"),
    _s("Financial Modeling", "domain", "Financial Modelling"), _s("Forecasting", "domain"),
    _s("Business Analysis", "domain"), _s("Requirements Gathering", "methodology"),
    _s("Supply Chain Management", "domain", "Supply Chain"), _s("Procurement", "domain"),
    _s("Logistics", "domain"), _s("Inventory Management", "domain"), _s("Operations Management", "domain"),
    _s("Digital Marketing", "domain"), _s("SEO", "domain", "Search Engine Optimization"),
    _s("Content Marketing", "domain"), _s("CRM", "tool"), _s("Salesforce", "tool"), _s("HubSpot", "tool"),
    _s("Sales", "domain", "Business Development"), _s("Customer Service", "domain", "Customer Support"),
    _s("Recruitment", "domain", "Talent Acquisition"), _s("Accounting", "domain"), _s("IFRS", "domain"),
    _s("Auditing", "domain"), _s("PMP", "domain"), _s("PRINCE2", "domain"), _s("ITIL", "domain"),
    _s("UX Design", "domain", "User Experience"), _s("UI Design", "domain"), _s("Figma", "tool"),
    _s("Microsoft Office", "tool", "MS Office"), _s("PowerPoint", "tool"),
    # Soft skills
    _s("Leadership", "soft", "Team Leadership"), _s("Communication", "soft", "Communication Skills"),
    _s("Teamwork", "soft", "Collaboration"), _s("Problem Solving", "soft", "Problem-solving"),
    _s("Critical Thinking", "soft"), _s("Time Management", "soft"), _s("Negotiation", "soft"),
    _s("Presentation Skills", "soft", "Public Speaking"), _s("Mentoring", "soft", "Coaching"),
    _s("Adaptability", "soft"), _s("Attention to Detail", "soft"), _s("Decision Making", "soft", "Decision-making"),
    _s("Conflict Resolution", "soft"), _s("Customer Focus", "soft"),
    # Languages
    _s("English", "language"), _s("Arabic", "language"), _s("Urdu", "language"), _s("French", "language"),
    _s("German", "language"), _s("Spanish", "language"), _s("Hindi", "language"), _s("Chinese", "language", "Mandarin"),
)

# Very short or ambiguous aliases that would cause false positives in prose; only matched in
# contexts that look like skill lists (comma/pipe/bullet separated) or with exact case.
_CASE_SENSITIVE = {"C", "R", "Go", "Lean", "Sales", "Spring", "Swift", "Rust", "ML", "JS", "5S", "Excel"}


@dataclass(frozen=True)
class SkillMatch:
    name: str
    category: Category
    matched_text: str


def _pattern(alias: str) -> str:
    escaped = re.escape(alias)
    # Word-ish boundaries that also work for names like C++, C#, .NET, CI/CD.
    return rf"(?<![A-Za-z0-9+#/.&]){escaped}(?![A-Za-z0-9+#&]|\.[A-Za-z0-9])"


@lru_cache(maxsize=1)
def _compiled() -> tuple[tuple[SkillDef, re.Pattern[str]], ...]:
    out = []
    for skill in TAXONOMY:
        aliases = (skill.name, *skill.aliases)
        insensitive = [a for a in aliases if a not in _CASE_SENSITIVE]
        sensitive = [a for a in aliases if a in _CASE_SENSITIVE]
        parts = []
        if insensitive:
            parts.append("(?i:" + "|".join(_pattern(a) for a in sorted(insensitive, key=len, reverse=True)) + ")")
        if sensitive:
            parts.append("|".join(_pattern(a) for a in sensitive))
        out.append((skill, re.compile("|".join(parts))))
    return tuple(out)


def extract_skills(text: str) -> list[SkillMatch]:
    """Return the distinct taxonomy skills mentioned in the text, in taxonomy order."""
    found: list[SkillMatch] = []
    for skill, pattern in _compiled():
        m = pattern.search(text)
        if m is None:
            continue
        if skill.name in {"C", "R", "Go"} and not _looks_like_list_context(text, m.start(), m.end()):
            continue
        found.append(SkillMatch(skill.name, skill.category, m.group(0)))
    return found


def _looks_like_list_context(text: str, start: int, end: int) -> bool:
    """Single-letter languages only count when they appear in a list (e.g. 'Python, R, SQL')."""
    before = text[max(0, start - 3):start]
    after = text[end:end + 3]
    seps = (",", "|", "/", ";", "•", "-", ":", "(")
    return any(s in before for s in seps) or any(s in after for s in (",", "|", "/", ";", ")"))


def skill_names(text: str) -> set[str]:
    return {m.name for m in extract_skills(text)}
