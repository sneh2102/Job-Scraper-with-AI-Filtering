from __future__ import annotations

import math
import re
import time
from datetime import datetime

from jobspy.util import extract_emails_from_text, markdown_converter, create_logger
from jobspy.model import (
    JobPost, Compensation, Location, JobResponse,
    Country, DescriptionFormat, Scraper, ScraperInput, Site,
    CompensationInterval,
)
from jobspy.ziprecruiter.util import get_job_type_enum

log = create_logger("ZipRecruiter")


class ZipRecruiter(Scraper):
    base_url      = "https://www.ziprecruiter.com"
    jobs_per_page = 20

    def __init__(self, proxies=None, ca_cert=None, user_agent=None):
        super().__init__(Site.ZIP_RECRUITER, proxies=proxies)
        self.scraper_input = None
        self.seen_urls     = set()
        self.delay         = 3

    # ── public ────────────────────────────────────────────────────────────────
    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        self.scraper_input = scraper_input
        job_list  = []
        max_pages = math.ceil(scraper_input.results_wanted / self.jobs_per_page)

        for page in range(1, max_pages + 1):
            if len(job_list) >= scraper_input.results_wanted:
                break
            log.info(f"ZipRecruiter: search page {page} / {max_pages}")
            jobs = self._scrape_page_playwright(scraper_input, page)
            if not jobs:
                log.info("ZipRecruiter: no jobs on page %d — stopping", page)
                break
            job_list.extend(jobs)
            if page < max_pages:
                time.sleep(self.delay)

        return JobResponse(jobs=job_list[: scraper_input.results_wanted])

    # ── playwright scraper ────────────────────────────────────────────────────
    def _scrape_page_playwright(self, scraper_input: ScraperInput, page: int) -> list[JobPost]:
        from playwright.sync_api import sync_playwright

        jobs     = []
        search   = scraper_input.search_term or ""
        location = scraper_input.location    or ""

        url = (
            f"{self.base_url}/jobs-search"
            f"?search={search.replace(' ', '+')}"
            f"&location={location.replace(' ', '+')}"
        )
        if scraper_input.is_remote:
            url += "&remote=true"
        if page > 1:
            url += f"&page={page}"

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                )
                web_page = context.new_page()

                log.info(f"ZipRecruiter: loading {url}")
                web_page.goto(url, wait_until="networkidle", timeout=30000)
                web_page.wait_for_timeout(3000)

                log.info(f"ZipRecruiter: page title = '{web_page.title()}'")

                # ── Save debug artifacts on first page ────────────────
                if page == 1:
                    try:
                        web_page.screenshot(path="ziprecruiter_debug.png")
                    except Exception:
                        pass

                # ── Strategy 1: Extract all job anchor hrefs directly ─
                # This is the most reliable — get real hrefs from the DOM
                raw_cards = web_page.evaluate("""
                    () => {
                        const cards = [];
                        const seen  = new Set();

                        // Try every anchor that looks like a job link
                        const anchors = [
                            ...document.querySelectorAll('a[href*="/jobs/"]'),
                            ...document.querySelectorAll('a[href*="/k/"]'),
                            ...document.querySelectorAll('a[data-href*="ziprecruiter"]'),
                        ];

                        anchors.forEach(a => {
                            try {
                                const href = a.href || '';
                                // Must be a ZipRecruiter job URL and not already seen
                                if (!href || seen.has(href)) return;
                                if (!href.includes('ziprecruiter.com')) return;
                                // Skip navigation/utility links
                                if (href.includes('/jobs-search') ||
                                    href.includes('/login') ||
                                    href.includes('/signup') ||
                                    href.includes('/privacy') ||
                                    href.includes('/terms')) return;

                                seen.add(href);

                                // Walk up to find the job card container
                                let container = a;
                                for (let i = 0; i < 6; i++) {
                                    if (!container.parentElement) break;
                                    container = container.parentElement;
                                    if (container.tagName === 'ARTICLE' ||
                                        container.getAttribute('data-job-id') ||
                                        container.id?.includes('job')) break;
                                }

                                // Extract fields from container or anchor itself
                                const getText = (el, ...selectors) => {
                                    for (const sel of selectors) {
                                        const found = el.querySelector(sel);
                                        if (found && found.innerText.trim()) {
                                            return found.innerText.trim();
                                        }
                                    }
                                    return null;
                                };

                                const title = getText(container,
                                    '[class*="title"]', 'h2', 'h3', 'h4',
                                    '[data-testid="job-card-title"]',
                                    '.job_title', '.title'
                                ) || a.innerText.trim() || null;

                                const company = getText(container,
                                    '[data-testid="job-card-company"]',
                                    '[class*="company"]',
                                    '.company_name', '.hiring_company'
                                );

                                const location = getText(container,
                                    '[data-testid="job-card-location"]',
                                    '[class*="location"]',
                                    '.location', '.job_location'
                                );

                                const salary = getText(container,
                                    '[class*="salary"]',
                                    '[data-testid*="salary"]',
                                    '.salary', '.compensation'
                                );

                                const date = getText(container,
                                    '[class*="date"]', 'time',
                                    '[data-testid*="date"]'
                                );

                                // Only push if we have at least a URL
                                if (href) {
                                    cards.push({
                                        url:      href,
                                        title:    title,
                                        company:  company,
                                        location: location,
                                        salary:   salary,
                                        date:     date,
                                    });
                                }
                            } catch(e) {}
                        });

                        return cards;
                    }
                """)

                log.info(f"ZipRecruiter: Strategy 1 found {len(raw_cards)} cards")

                # ── Strategy 2: article-based extraction ──────────────
                if not raw_cards:
                    log.warning("Strategy 1 failed — trying article selector")
                    raw_cards = web_page.evaluate("""
                        () => {
                            const cards = [];
                            const articles = document.querySelectorAll('article');
                            articles.forEach(article => {
                                try {
                                    // Get first anchor in or near article
                                    const a = article.querySelector('a') ||
                                              article.closest('a');
                                    const href = a?.href || '';
                                    if (!href.includes('ziprecruiter.com')) return;

                                    const title = (
                                        article.querySelector('h2, h3, h4')?.innerText ||
                                        a?.innerText || ''
                                    ).trim();

                                    const allText = article.innerText || '';
                                    cards.push({
                                        url:      href,
                                        title:    title || null,
                                        company:  null,
                                        location: null,
                                        salary:   null,
                                        date:     null,
                                    });
                                } catch(e) {}
                            });
                            return cards;
                        }
                    """)
                    log.info(f"ZipRecruiter: Strategy 2 found {len(raw_cards)} cards")

                # ── Strategy 3: JSON-LD structured data ───────────────
                if not raw_cards:
                    log.warning("Strategy 2 failed — trying JSON-LD")
                    raw_cards = web_page.evaluate("""
                        () => {
                            const jobs = [];
                            document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
                                try {
                                    const d     = JSON.parse(s.textContent);
                                    const items = d['@graph'] || (Array.isArray(d) ? d : [d]);
                                    items.forEach(item => {
                                        if (item['@type'] === 'JobPosting') {
                                            jobs.push({
                                                title:    item.title           || null,
                                                company:  item.hiringOrganization?.name || null,
                                                location: item.jobLocation?.address?.addressLocality || null,
                                                url:      item.url             || null,
                                                salary:   null,
                                                date:     item.datePosted      || null,
                                            });
                                        }
                                    });
                                } catch(e) {}
                            });
                            return jobs;
                        }
                    """)
                    log.info(f"ZipRecruiter: Strategy 3 (JSON-LD) found {len(raw_cards)} jobs")

                # ── Strategy 4: log all hrefs for debugging ───────────
                if not raw_cards:
                    log.warning("All strategies failed — logging sample hrefs for debug")
                    sample = web_page.evaluate("""
                        () => [...document.querySelectorAll('a')]
                              .map(a => a.href)
                              .filter(h => h && h.includes('ziprecruiter'))
                              .slice(0, 10)
                    """)
                    log.info("Sample hrefs on page: %s", sample)

                browser.close()

                for card in raw_cards:
                    job = self._parse_card(card)
                    if job:
                        jobs.append(job)

        except Exception as e:
            log.error(f"ZipRecruiter Playwright error: {e}")

        return jobs

    # ── card parser ───────────────────────────────────────────────────────────
    def _parse_card(self, card: dict) -> JobPost | None:
        try:
            job_url = (card.get("url") or "").strip()
            if not job_url:
                return None

            # Clean up URL — remove tracking params but keep the path
            # Real ZipRecruiter job URLs look like:
            # https://www.ziprecruiter.com/jobs/Company-Name/Job-Title/hash
            # https://www.ziprecruiter.com/k/l/search?...  ← search pages, skip
            if any(x in job_url for x in [
                "/jobs-search", "/candidate/", "/login",
                "/signup", "/privacy", "/terms", "?search=",
            ]):
                return None

            # Strip UTM/tracking params
            if "?" in job_url:
                base = job_url.split("?")[0]
                # Keep only if it's a job detail page
                if "/jobs/" in base or "/k/" in base:
                    job_url = base
                # Otherwise keep full URL
                else:
                    job_url = job_url

            if job_url in self.seen_urls:
                return None
            self.seen_urls.add(job_url)

            title   = (card.get("title") or "N/A").strip()
            company = card.get("company")
            loc_str = (card.get("location") or "").strip()

            # Parse location
            city = state = None
            if "," in loc_str:
                parts = [p.strip() for p in loc_str.split(",")]
                city  = parts[0]
                state = parts[1] if len(parts) > 1 else None
            elif loc_str:
                city = loc_str

            # Detect country
            country_enum = Country.USA
            ca_indicators = ["Canada", " ON", " BC", " AB", " QC", " NS",
                             " NB", " MB", " SK", " PE", " NL", " NT", " YT", " NU"]
            if any(x in loc_str for x in ca_indicators):
                country_enum = Country.CANADA

            # Parse date
            date_posted = None
            raw_date    = card.get("date")
            if raw_date:
                for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%B %d, %Y"):
                    try:
                        date_posted = datetime.strptime(raw_date[:10], fmt[:10]).date()
                        break
                    except Exception:
                        continue

            is_remote = (
                "remote" in loc_str.lower() or
                "remote" in title.lower()
            )

            return JobPost(
                id=f"zr-{abs(hash(job_url))}",
                title=title,
                company_name=company,
                location=Location(city=city, state=state, country=country_enum),
                job_url=job_url,
                date_posted=date_posted,
                compensation=self._parse_salary(card.get("salary")),
                is_remote=is_remote,
            )

        except Exception as e:
            log.warning(f"ZipRecruiter card parse error: {e}")
            return None

    # ── salary parser ─────────────────────────────────────────────────────────
    @staticmethod
    def _parse_salary(salary_str: str | None) -> Compensation | None:
        if not salary_str:
            return None
        try:
            nums = re.findall(r"[\d,]+", salary_str)
            if len(nums) < 2:
                return None
            mn = int(nums[0].replace(",", ""))
            mx = int(nums[1].replace(",", ""))
            if salary_str.lower().count("hour") > 0:
                interval = CompensationInterval.HOURLY
            elif salary_str.lower().count("month") > 0:
                interval = CompensationInterval.MONTHLY
            elif salary_str.lower().count("week") > 0:
                interval = CompensationInterval.WEEKLY
            else:
                interval = CompensationInterval.YEARLY
            return Compensation(
                interval=interval, min_amount=mn, max_amount=mx, currency="USD"
            )
        except Exception:
            return None