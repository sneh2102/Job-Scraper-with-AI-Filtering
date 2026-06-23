"""
jobs_scraper.py
===============
Unified job scraping entry point for JobHunter.

Supported sites via jobspy:    indeed, glassdoor, linkedin, jobright, naukri, zip_recruiter
Supported sites standalone:    wellfound

Usage:
    from jobs_scraper import scrape_all_jobs

    df = scrape_all_jobs(
        site_name      = "indeed,wellfound",
        search_term    = "Software Developer",
        location       = "Canada",
        hours_old      = "72",
        results_wanted = "20",
        country_indeed = "canada",
        is_remote      = False,
    )
"""

import logging
import os
import pandas as pd

log = logging.getLogger("jobs_scraper")


def scrape_all_jobs(
    site_name:      str  = "indeed,glassdoor,jobright",
    search_term:    str  = "Software Developer",
    location:       str  = "Canada",
    hours_old:      str  = "72",
    results_wanted: str  = "20",
    country_indeed: str  = "canada",
    is_remote:      bool = False,
    offset:         int  = 0,
    linkedin_fetch_description: bool = True,
) -> pd.DataFrame:
    """
    Scrapes jobs from all requested sites and returns a unified DataFrame.
    Wellfound is handled separately from jobspy because it requires Playwright.
    """
    sites        = [s.strip().lower() for s in site_name.split(",") if s.strip()]
    n_wanted     = int(results_wanted)
    n_hours      = int(hours_old)

    # Split into jobspy-native vs wellfound
    wellfound_sites = [s for s in sites if s == "wellfound"]
    jobspy_sites    = [s for s in sites if s != "wellfound"]

    frames: list[pd.DataFrame] = []

    # ── jobspy sites ──────────────────────────────────────────────────────────
    if jobspy_sites:
        try:
            from jobspy import scrape_jobs
            log.info("Scraping via jobspy: %s", jobspy_sites)
            df = scrape_jobs(
                site_name      = jobspy_sites,
                search_term    = search_term,
                location       = location,
                hours_old      = n_hours,
                results_wanted = n_wanted,
                country_indeed = country_indeed,
                is_remote      = is_remote,
                offset         = offset,
                linkedin_fetch_description = linkedin_fetch_description,
            )
            if df is not None and not df.empty:
                df["site"] = df.get("site", "").fillna(",".join(jobspy_sites))
                frames.append(df)
                log.info("jobspy returned %d jobs", len(df))
        except Exception as e:
            log.error("jobspy scraping failed: %s", e)

    # ── Wellfound ─────────────────────────────────────────────────────────────
    if wellfound_sites:
        try:
            log.info("Scraping Wellfound (Playwright)...")
            from jobspy.wellfound import WellfoundScraper

            scraper = WellfoundScraper()
            raw     = scraper.scrape(
                search_term        = search_term,
                location           = location,
                results_wanted     = n_wanted,
                hours_old          = n_hours,
                is_remote          = is_remote,
                fetch_descriptions = linkedin_fetch_description,
            )

            if raw:
                wf_df = pd.DataFrame(raw)
                # Normalise column names to match jobspy's DataFrame schema
                wf_df = wf_df.rename(columns={
                    "company":     "company",
                    "job_url":     "job_url",
                    "date_posted": "date_posted",
                })
                frames.append(wf_df)
                log.info("Wellfound returned %d jobs", len(wf_df))
            else:
                log.info("Wellfound returned 0 jobs")

        except Exception as e:
            log.error("Wellfound scraping failed: %s", e)
            import traceback
            log.debug(traceback.format_exc())

    # ── Merge ─────────────────────────────────────────────────────────────────
    if not frames:
        log.warning("No jobs collected from any site")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)

    # Ensure all expected columns exist (fill missing with empty string)
    expected_cols = [
        "title", "company", "job_url", "location", "description",
        "date_posted", "compensation", "is_remote", "job_type",
        "site", "company_url",
        # Naukri-specific (empty for other sites)
        "experience_range", "vacancy_count", "company_rating",
        "company_reviews_count", "work_from_home_type",
    ]
    for col in expected_cols:
        if col not in combined.columns:
            combined[col] = ""

    log.info("Total jobs collected: %d", len(combined))
    return combined