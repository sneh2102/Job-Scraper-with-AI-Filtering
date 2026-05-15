# jobs_scraper.py
import sys
import os
import logging

# ── Use local jobspy (with all custom fixes) ──────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jobspy import scrape_jobs

def scrape_all_jobs(
    site_name,
    search_term,
    location,
    hours_old,
    results_wanted,
    offset=0,
    google_search_term=None,
    country_indeed="canada",
    is_remote=False,
):
    # Normalize sites
    if isinstance(site_name, str):
        sites = [s.strip().lower() for s in site_name.split(",") if s.strip()]
    elif isinstance(site_name, list):
        sites = [str(s).strip().lower() for s in site_name]
    else:
        sites = ["indeed", "glassdoor", "jobright"]

    if not sites:
        sites = ["indeed", "glassdoor", "jobright"]

    # Remove unsupported sites
    supported = {"indeed", "glassdoor", "linkedin", "zip_recruiter",
                 "google", "jobright", "naukri", "bayt", "bdjobs"}
    valid_sites = [s for s in sites if s in supported]
    dropped = [s for s in sites if s not in supported]
    if dropped:
        logging.warning("Dropping unsupported sites: %s", dropped)
    if not valid_sites:
        valid_sites = ["indeed", "glassdoor"]

    logging.info(
        "Scraping %s | search='%s' | location='%s' | country='%s' | hours_old=%s",
        valid_sites, search_term, location, country_indeed, hours_old
    )

    return scrape_jobs(
        site_name=valid_sites,
        search_term=search_term,
        google_search_term=google_search_term,
        location=location,
        distance=100,
        is_remote=is_remote,
        results_wanted=int(results_wanted) if results_wanted else 20,
        offset=int(offset) if offset else 0,
        hours_old=int(hours_old) if hours_old else 72,
        country_indeed=country_indeed,
        linkedin_fetch_description=True,
        description_format="markdown",
        verbose=1,
    )