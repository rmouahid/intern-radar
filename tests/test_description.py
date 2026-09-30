# ruff: noqa: E501 -- fixtures reproduce real posting lines verbatim

from intern_radar.description import clean_description

GREENHOUSE = """Company Description:
At Acme, we build the best data platform in the world for everyone.
We are growing fast.
Job description:
You will fine-tune LLMs for enterprise domains.
Requirements:
Currently enrolled in a Master's program; available for 6 months.
Benefits
Free lunch and gym.
Acme is an equal opportunity employer and considers applicants without regard to race.
"""

AMAZON = """There’s a universe of opportunity at Acme.
At Acme, your career doesn’t follow a straight line.
What’s in it for you?
An internship at Acme means real responsibility from day one.
Key job responsibilities
Build ML pipelines.
Basic qualifications
- Enrolled in a Master's degree
Acme is an equal opportunities employer.
Our inclusive culture empowers Acmers. If you have a disability, contact us.
"""

WORKDAY = """By submitting your resume, you acknowledge that your application will be processed per the Applicant Privacy Policy.
Acme pioneered accelerated computing.
What you’ll be doing:
Develop GPU runtime components.
What we need to see:
Pursuing an MS in Computer Science.
Ways to stand out from the crowd:
CUDA experience.
The base salary range is 20 USD - 40 USD per hour.
"""

LEVER = """A World-Changing Company

Acme builds software for data-driven decisions.

The Role

As an intern you will deploy software against hard problems.

Core Requirements

Strong analytical skills.

Salary
The estimated salary range for this position is $8,000/month.
"""

SMARTRECRUITERS = """💼 Role Overview
Join Acme as an ML intern.
🎯 Key Responsibilities
Train vision models.
🎁 What We Offer
Transport allowance.
✅ Your Profile
Python, PyTorch.
"""


def test_greenhouse_sections():
    cleaned = clean_description(GREENHOUSE)
    assert "fine-tune LLMs" in cleaned and "6 months" in cleaned
    assert "best data platform" not in cleaned
    assert "Free lunch" not in cleaned and "equal opportunity" not in cleaned


def test_amazon_keeps_responsibilities_and_qualifications():
    cleaned = clean_description(AMAZON)
    assert "Build ML pipelines." in cleaned and "Master's degree" in cleaned
    assert "real responsibility from day one" not in cleaned
    assert "straight line" not in cleaned and "universe" not in cleaned
    assert "equal opportunities" not in cleaned and "disability" not in cleaned


def test_workday_drops_legal_lines_but_keeps_the_role():
    cleaned = clean_description(WORKDAY)
    assert "Applicant Privacy" not in cleaned and "salary range" not in cleaned
    assert "GPU runtime" in cleaned and "CUDA experience." in cleaned


def test_lever_unknown_heading_continues_the_kept_section():
    cleaned = clean_description(LEVER)
    assert "data-driven decisions" not in cleaned
    assert "deploy software" in cleaned and "Strong analytical skills." in cleaned
    assert "$8,000" not in cleaned


def test_emoji_headings_are_recognised():
    cleaned = clean_description(SMARTRECRUITERS)
    assert "Train vision models." in cleaned and "PyTorch" in cleaned
    assert "Transport allowance" not in cleaned


def test_about_the_role_is_not_company_boilerplate():
    text = "About Acme\nWe sell rockets.\nAbout the role\nBuild ML models."
    assert clean_description(text) == "About the role\nBuild ML models."


def test_blank_and_repeated_lines_are_collapsed():
    assert clean_description("Build\n\n\nBuild\n  Test  \n") == "Build\nTest"


def test_never_returns_an_empty_description():
    text = "Benefits\nFree lunch."
    assert clean_description(text) == text
    assert clean_description("") == ""


def test_team_and_programme_sections_describe_the_role():
    text = (
        "About Acme\nWe sell rockets.\n"
        "About the team\nWe build GPU compilers.\n"
        "About the Investment Services Internship\nRotate across desks."
    )
    cleaned = clean_description(text)
    assert "rockets" not in cleaned
    assert "GPU compilers" in cleaned and "Rotate across desks." in cleaned


def test_duration_lines_survive_inside_dropped_sections():
    text = (
        "Benefits\nFree lunch.\n"
        "Our summer program runs for 12 weeks from June 2027.\n"
        "Weekly office hours with mentors."
    )
    cleaned = clean_description(text)
    assert cleaned == "Our summer program runs for 12 weeks from June 2027."
