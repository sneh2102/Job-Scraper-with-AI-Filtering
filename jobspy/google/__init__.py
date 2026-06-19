from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timedelta

from jobspy.model import (
    Scraper,
    ScraperInput,
    Site,
    JobPost,
    JobResponse,
    Location,
    JobType,
)
from jobspy.util import extract_emails_from_text, extract_job_type
from jobspy.google.util import log, find_job_info_initial_page, find_job_info

# JavaScript run inside Playwright to extract job cards from the rendered DOM.
# Selectors confirmed from live Google Jobs HTML (June 2025):
#   Card container : [data-preview-id]
#   Title          : .tNxQIb.PUpOsf
#   Company        : .wHYlTd.MKCbgd.a3jPc
#   Location+source: .wHYlTd.FqK3wc.MKCbgd
#   Date           : span.Yf9oye  (inner span.Yf9oye > span[aria-hidden])
_EXTRACT_JS = """
() => {
    const results = [];
    const seen = new Set();
    const baseUrl = 'https://www.google.com/search';

    const cards = Array.from(document.querySelectorAll('[data-preview-id]'));
    for (const card of cards) {
        const previewId = card.getAttribute('data-preview-id') || '';

        const titleEl   = card.querySelector('.tNxQIb.PUpOsf');
        const compEl    = card.querySelector('.wHYlTd.MKCbgd.a3jPc');
        const locEl     = card.querySelector('.wHYlTd.FqK3wc.MKCbgd');
        const dateEl    = card.querySelector('span.Yf9oye span[aria-hidden]');
        const salaryEl  = card.querySelector('.I2Cbhb');

        const title    = titleEl  ? titleEl.innerText.trim()  : null;
        const company  = compEl   ? compEl.innerText.trim()   : null;
        const locRaw   = locEl    ? locEl.innerText.trim()    : '';
        const date     = dateEl   ? dateEl.innerText.trim()   : null;
        const salary   = salaryEl ? salaryEl.innerText.trim() : null;

        if (!title || !company) continue;
        const key = title + '|' + company;
        if (seen.has(key)) continue;
        seen.add(key);

        // Location and via-source are in the same element separated by " • via "
        let location = locRaw, source = '';
        const viaIdx = locRaw.indexOf(' via ');
        if (viaIdx > -1) {
            location = locRaw.substring(0, viaIdx).trim();
            source   = locRaw.substring(viaIdx + 5).trim();
        }
        // Clean up bullet separator that sometimes appears
        location = location.replace(/[•∙]/g, '').trim();

        // Build a Google Jobs detail URL from the preview ID
        const jobUrl = previewId
            ? baseUrl + '?q=' + encodeURIComponent(title + ' ' + company) + '&udm=8&jid=' + previewId
            : baseUrl + '?q=' + encodeURIComponent(title + ' ' + company + ' jobs') + '&udm=8';

        results.push({ title, company, location, source, date, salary, url: jobUrl, previewId });
    }
    return results;
}
"""

_MORE_BTN_JS = """
() => {
    // Google 2025: the 'More jobs' button lives near [jsname='iTtkOe']
    // Also try any visible button / div with 'More jobs' text
    const candidates = Array.from(document.querySelectorAll('[role="button"], button, a'));
    for (const el of candidates) {
        const txt = (el.innerText || el.textContent || '').trim();
        if (txt === 'More jobs' && el.offsetParent !== null) {
            el.click();
            return true;
        }
    }
    return false;
}
"""


class Google(Scraper):
    def __init__(
        self,
        proxies: list[str] | str | None = None,
        ca_cert: str | None = None,
        user_agent: str | None = None,
    ):
        site = Site(Site.GOOGLE)
        super().__init__(site, proxies=proxies, ca_cert=ca_cert)

        self.country = None
        self.session = None
        self.scraper_input = None
        self.jobs_per_page = 10
        self.seen_urls: set[str] = set()
        self.url = "https://www.google.com/search"
        self.jobs_url = "https://www.google.com/async/callback:550"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        import os
        from pathlib import Path
        from playwright.sync_api import sync_playwright

        self.scraper_input = scraper_input
        results_wanted = min(100, scraper_input.results_wanted)

        search_url = self._build_url()
        log.info(f"Google: navigating to {search_url}")

        # Persistent profile so cookies / solved CAPTCHAs survive across runs
        profile_dir = str(Path.home() / ".jobspy_google_profile")
        os.makedirs(profile_dir, exist_ok=True)

        _LAUNCH_ARGS = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--window-position=0,0",
            "--ignore-certificate-errors",
        ]
        _UA = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )

        jobs: list[JobPost] = []

        with sync_playwright() as p:
            # launch_persistent_context keeps cookies / localStorage between runs
            context = p.chromium.launch_persistent_context(
                profile_dir,
                headless=False,
                args=_LAUNCH_ARGS,
                user_agent=_UA,
                viewport={"width": 1280, "height": 900},
                locale="en-US",
                timezone_id="America/Toronto",
            )
            # Hide the automation flag that Google detects
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = context.new_page()
            try:
                page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)

                # If Google shows a CAPTCHA the user can solve it manually (headless=False).
                # Wait up to 90 s for the page title to stop being a challenge page.
                try:
                    page.wait_for_function(
                        """document.title &&
                           !document.title.toLowerCase().includes('captcha') &&
                           !document.title.toLowerCase().includes('unusual traffic') &&
                           document.title !== 'Just a moment...'""",
                        timeout=90_000,
                    )
                except Exception:
                    log.warning("Google: CAPTCHA / challenge may still be present — proceeding anyway")

                page.wait_for_timeout(2_500)

                page_num = 1
                while len(jobs) < results_wanted:
                    log.info(f"Google: parsing page {page_num}")
                    new_jobs = self._scrape_page(page)
                    for j in new_jobs:
                        if j.job_url not in self.seen_urls:
                            self.seen_urls.add(j.job_url)
                            jobs.append(j)

                    if len(jobs) >= results_wanted:
                        break
                    if not self._click_more(page):
                        break
                    page_num += 1

            except Exception as exc:
                log.error(f"Google scrape error: {exc}")
            finally:
                context.close()

        log.info(f"Google: collected {len(jobs)} jobs")
        offset = scraper_input.offset
        return JobResponse(jobs=jobs[offset: offset + results_wanted])

    # ------------------------------------------------------------------
    # Per-page extraction: JSON first, DOM fallback
    # ------------------------------------------------------------------

    def _scrape_page(self, page) -> list[JobPost]:
        html = page.content()

        # Try Google's internal JSON format (works when page is rendered by a real browser)
        json_jobs = self._extract_from_json(html)
        if json_jobs:
            log.info(f"Google: extracted {len(json_jobs)} jobs via JSON")
            return json_jobs

        # Fall back to DOM extraction
        dom_jobs = self._extract_from_dom(page)
        log.info(f"Google: extracted {len(dom_jobs)} jobs via DOM")
        return dom_jobs

    def _extract_from_json(self, html: str) -> list[JobPost]:
        jobs_raw = find_job_info_initial_page(html)
        jobs = []
        for raw in jobs_raw:
            try:
                job = self._parse_json_job(raw)
                if job:
                    jobs.append(job)
            except Exception as exc:
                log.debug(f"JSON job parse error: {exc}")
        return jobs

    def _extract_from_dom(self, page) -> list[JobPost]:
        try:
            raw_list = page.evaluate(_EXTRACT_JS) or []
        except Exception as exc:
            log.warning(f"DOM JS evaluate error: {exc}")
            raw_list = []

        now = datetime.now()
        jobs = []
        for rd in raw_list:
            try:
                job = self._parse_dom_job(rd, now)
                if job:
                    jobs.append(job)
            except Exception as exc:
                log.debug(f"DOM job parse error: {exc}")
        return jobs

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _click_more(self, page) -> bool:
        try:
            clicked = page.evaluate(_MORE_BTN_JS)
            if clicked:
                page.wait_for_timeout(2_500)
                return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # Job parsers
    # ------------------------------------------------------------------

    def _parse_json_job(self, job_info: list) -> JobPost | None:
        """Parse Google's internal positional JSON array. Uses safe access throughout."""
        def safe(*indices, default=None):
            try:
                v = job_info
                for i in indices:
                    v = v[i]
                return v
            except (IndexError, TypeError, KeyError):
                return default

        job_url = safe(3, 0, 0)
        if not job_url:
            return None

        title        = safe(0,  default="")
        company_name = safe(1,  default="")
        location_str = safe(2,  default="") or ""
        days_ago_raw = safe(12, default=None)
        description  = safe(19, default="") or ""
        job_id_raw   = safe(28, default=job_url)

        city = state = country = None
        if location_str and "," in location_str:
            parts = [p.strip() for p in location_str.split(",")]
            city    = parts[0]
            state   = parts[1] if len(parts) > 1 else None
            country = parts[2] if len(parts) > 2 else None
        else:
            city = location_str

        date_posted = None
        if isinstance(days_ago_raw, str):
            m = re.search(r"\d+", days_ago_raw)
            if m:
                date_posted = (datetime.now() - timedelta(days=int(m.group()))).date()

        return JobPost(
            id=f"go-{job_id_raw}",
            title=title,
            company_name=company_name,
            location=Location(city=city, state=state, country=country),
            job_url=job_url,
            date_posted=date_posted,
            is_remote="remote" in description.lower() or "wfh" in description.lower(),
            description=description,
            emails=extract_emails_from_text(description),
            job_type=extract_job_type(description),
        )

    def _parse_dom_job(self, rd: dict, now: datetime) -> JobPost | None:
        title        = (rd.get("title")    or "").strip()
        company_name = (rd.get("company")  or "").strip()
        if not title or not company_name:
            return None

        location_str = (rd.get("location")    or "").strip()
        date_str     = (rd.get("date")        or "").strip()
        url          = (rd.get("url")         or "").strip()
        description  = (rd.get("description") or "").strip()
        salary_str   = (rd.get("salary")      or "").strip()

        city = state = country = None
        if location_str:
            parts = [p.strip() for p in re.split(r"[,·•]", location_str)]
            city    = parts[0] if parts else None
            state   = parts[1] if len(parts) > 1 else None
            country = parts[2] if len(parts) > 2 else None

        date_posted = None
        if date_str:
            m = re.search(r"(\d+)\s*(hour|day|week|month)", date_str, re.IGNORECASE)
            if m:
                n, unit = int(m.group(1)), m.group(2).lower()
                deltas = {
                    "hour":  timedelta(hours=n),
                    "day":   timedelta(days=n),
                    "week":  timedelta(weeks=n),
                    "month": timedelta(days=n * 30),
                }
                date_posted = (now - deltas[unit]).date()
            elif re.search(r"just.?posted|today", date_str, re.IGNORECASE):
                date_posted = now.date()

        if date_posted and self.scraper_input and self.scraper_input.hours_old:
            cutoff = (now - timedelta(hours=self.scraper_input.hours_old)).date()
            if date_posted < cutoff:
                return None

        job_id = f"go-{abs(hash(url + title)) % 10 ** 8:08d}"

        return JobPost(
            id=job_id,
            title=title,
            company_name=company_name,
            location=Location(city=city, state=state, country=country),
            job_url=url or self.url,
            date_posted=date_posted,
            is_remote="remote" in (description + location_str).lower(),
            description=description,
            emails=extract_emails_from_text(description),
            job_type=extract_job_type(description),
        )

    # ------------------------------------------------------------------
    # URL builder
    # ------------------------------------------------------------------

    def _build_url(self) -> str:
        si = self.scraper_input

        if si.google_search_term:
            query = si.google_search_term
        else:
            parts = [si.search_term]
            if si.location:
                parts.append(si.location)
            if si.is_remote:
                parts.append("remote")
            job_type_labels = {
                JobType.FULL_TIME:   "full time",
                JobType.PART_TIME:   "part time",
                JobType.INTERNSHIP:  "internship",
                JobType.CONTRACT:    "contract",
            }
            if si.job_type in job_type_labels:
                parts.append(job_type_labels[si.job_type])
            query = " ".join(parts) + " jobs"

        params: dict = {"q": query, "udm": "8", "hl": "en", "gl": "us"}

        if si.hours_old:
            days = max(1, si.hours_old // 24)
            if days == 1:
                params["tbs"] = "qdr:d"
            elif days <= 7:
                params["tbs"] = f"qdr:d{days}"
            elif days <= 30:
                params["tbs"] = "qdr:w"
            else:
                params["tbs"] = "qdr:m"

        return self.url + "?" + urllib.parse.urlencode(params)
