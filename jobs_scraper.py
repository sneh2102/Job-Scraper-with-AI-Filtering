# jobs_scraper.py
import logging
from jobspy import scrape_jobs
try:
    # Newer jobspy exposes Site enum here; if not, this import may fail (we handle below)
    from jobspy import Site
except Exception:
    Site = None  # fallback when enum isn't exposed

def _normalize_sites(site_name):
    """
    Accepts comma-delimited string or list, returns list of valid site names
    for the installed jobspy version. Unknown sites are dropped with a warning.
    """
    if isinstance(site_name, str):
        raw = [s.strip() for s in site_name.split(",") if s.strip()]
    elif isinstance(site_name, list):
        raw = [str(s).strip() for s in site_name if str(s).strip()]
    else:
        raw = []

    # default to all commonly supported on many versions if nothing provided
    if not raw:
        raw = ["indeed", "linkedin", "zip_recruiter", "glassdoor", "naukri", "bayt", "bdjobs"]  # omit 'google' by default

    # If enum available, filter by it; otherwise return raw (best effort)
    if Site is not None:
        supported = {m.name.lower() for m in Site}  # enum member names
        valid = []
        dropped = []
        for s in raw:
            s_up = s.replace("-", "_").lower()
            if s_up in supported:
                valid.append(s_up)
            else:
                dropped.append(s)
        if dropped:
            logging.warning("Dropping unsupported sites for this jobspy build: %s", ", ".join(dropped))
        if not valid:
            logging.warning("No valid sites left; falling back to ['indeed','linkedin','zip_recruiter']")
            valid = ["indeed", "linkedin", "zip_recruiter"]
        return valid
    else:
        # No enum available; best effort (and avoid 'google' which is known to break on some versions)
        if "google" in raw:
            logging.warning("Dropping 'google' (not supported on this jobspy version).")
            raw = [s for s in raw if s.lower() != "google"]
        return raw

def scrape_all_jobs(site_name, search_term, location, hours_old, results_wanted, offset=0,
                    google_search_term=None, country_indeed="India"):
    site_list = _normalize_sites(site_name)

    # IMPORTANT: do NOT hardcode sites here; use the validated site_list
    return scrape_jobs(
        site_name=site_list,
        search_term=search_term,
        google_search_term=google_search_term,  # Only used if 'google' supported
        location=location,
        distance=1000,
        results_wanted=int(results_wanted) if results_wanted else 50,
        offset=int(offset) if offset else 0,
        hours_old=int(hours_old) if hours_old else 72,
        country_indeed=country_indeed,
        linkedin_fetch_description=True,
        # proxies=[...]
    )
