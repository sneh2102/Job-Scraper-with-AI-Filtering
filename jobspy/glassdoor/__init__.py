from __future__ import annotations

import re
import json
import requests
from typing import Tuple
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from jobspy.glassdoor.cookie_fetcher import get_glassdoor_cookies_and_token
from jobspy.glassdoor.cookie_fetcher import get_glassdoor_cookies_and_token, get_glassdoor_location
from jobspy.glassdoor.constant import fallback_token, query_template, headers
from jobspy.glassdoor.util import (
    get_cursor_for_page,
    parse_compensation,
    parse_location,
)
from jobspy.util import (
    extract_emails_from_text,
    create_logger,
    create_session,
    markdown_converter,
)
from jobspy.exception import GlassdoorException
from jobspy.model import (
    JobPost,
    JobResponse,
    DescriptionFormat,
    Scraper,
    ScraperInput,
    Site,
)

log = create_logger("Glassdoor")
KNOWN_LOCATIONS = {
    # ── Canada — Verified from glassdoor.ca URLs ────────────────────
    "toronto":       (2281069, "CITY"),
    "vancouver":     (2278756, "CITY"),
    "halifax":       (2290928, "CITY"),
    "montreal":      (2296722, "CITY"),
    "calgary":       (2275123, "CITY"),
    "ottawa":        (2286068, "CITY"),
    "canada":        (16,      "COUNTRY"),

    # ── Canada Atlantic ─────────────────────────────────────────────
    "dartmouth":     (2290928, "CITY"),   # same metro as Halifax for now
    "nova scotia":   (13069,   "STATE"),
    "new brunswick": (13064,   "STATE"),
    "pei":           (13068,   "STATE"),
    "prince edward island": (13068, "STATE"),
    "newfoundland":  (13065,   "STATE"),

    # ── India ───────────────────────────────────────────────────────
    "india":         (115,     "COUNTRY"),

    # ── USA ─────────────────────────────────────────────────────────
    "new york":      (1132348, "CITY"),
    "san francisco": (1147401, "CITY"),
    "seattle":       (1150505, "CITY"),
    "chicago":       (1128808, "CITY"),
    "austin":        (1139761, "CITY"),
    "remote":        (11047,   "STATE"),
}
class Glassdoor(Scraper):
    def __init__(
        self, proxies: list[str] | str | None = None, ca_cert: str | None = None, user_agent: str | None = None
    ):
        """
        Initializes GlassdoorScraper with the Glassdoor job search url
        """
        site = Site(Site.GLASSDOOR)
        super().__init__(site, proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)

        self.base_url = None
        self.country = None
        self.session = None
        self.scraper_input = None
        self.jobs_per_page = 30
        self.max_pages = 30
        self.seen_urls = set()





    def scrape(self, scraper_input: ScraperInput) -> JobResponse:
        self.scraper_input = scraper_input
        self.scraper_input.results_wanted = min(900, scraper_input.results_wanted)
        self.base_url = self.scraper_input.country.get_glassdoor_url()

        self.session = create_session(
            proxies=self.proxies, ca_cert=self.ca_cert, has_retry=True, is_tls=False
        )

        log.info("Fetching Glassdoor cookies via browser...")
        try:
            cookies, token, ua = get_glassdoor_cookies_and_token()
            self.session.cookies.update(cookies)
            # CRITICAL: use same UA as browser so cf_clearance validates
            headers["user-agent"] = ua
            headers["gd-csrf-token"] = token if token else fallback_token
            log.info(f"Got {len(cookies)} cookies, token: {'found' if token else 'fallback'}")
        except Exception as e:
            log.warning(f"Browser fetch failed: {e}")
            headers["gd-csrf-token"] = fallback_token

        if self.user_agent:
            headers["user-agent"] = self.user_agent
        self.session.headers.update(headers)

        location_id, location_type = self._get_location(
            scraper_input.location, scraper_input.is_remote
        )
        if location_type is None:
            log.error("Glassdoor: location not parsed")
            return JobResponse(jobs=[])

        job_list: list[JobPost] = []
        cursor = None
        range_start = 1 + (scraper_input.offset // self.jobs_per_page)
        tot_pages = (scraper_input.results_wanted // self.jobs_per_page) + 2
        range_end = min(tot_pages, self.max_pages + 1)

        for page in range(range_start, range_end):
            log.info(f"search page: {page} / {range_end - 1}")
            try:
                jobs, cursor = self._fetch_jobs_page(
                    scraper_input, location_id, location_type, page, cursor
                )
                job_list.extend(jobs)
                if not jobs or len(job_list) >= scraper_input.results_wanted:
                    job_list = job_list[: scraper_input.results_wanted]
                    break
            except Exception as e:
                log.error(f"Glassdoor: {str(e)}")
                break

        return JobResponse(jobs=job_list)

    def _fetch_jobs_page(self, scraper_input, location_id, location_type, page_num, cursor):
        jobs = []
        self.scraper_input = scraper_input
        try:
            payload = self._add_payload(location_id, location_type, page_num, cursor)
            response = self.session.post(
                f"{self.base_url}/graph",
                timeout=15,
                data=payload,
            )
            if response.status_code != 200:
                raise GlassdoorException(f"bad response status code: {response.status_code}")
            res_json = response.json()[0]
            if "errors" in res_json:
                # Only fail on critical errors — seoData errors are non-critical
                critical = [
                    e for e in res_json["errors"]
                    if "jobsPageSeoData" not in str(e.get("path", []))
                    and "jobSerpJobOutlook" not in str(e.get("path", []))
                ]
                if critical:
                    raise ValueError(f"Critical API errors: {critical}")
                else:
                    log.warning(f"Non-critical API errors ignored: {[e['path'] for e in res_json['errors']]}")
        except (requests.exceptions.ReadTimeout, GlassdoorException, ValueError, Exception) as e:
            log.error(f"Glassdoor: {str(e)}")
            return jobs, None

        jobs_data = res_json["data"]["jobListings"]["jobListings"]
        with ThreadPoolExecutor(max_workers=self.jobs_per_page) as executor:
            future_to_job_data = {executor.submit(self._process_job, job): job for job in jobs_data}
            for future in as_completed(future_to_job_data):
                try:
                    job_post = future.result()
                    if job_post:
                        jobs.append(job_post)
                except Exception as exc:
                    raise GlassdoorException(f"Glassdoor generated an exception: {exc}")

        return jobs, get_cursor_for_page(
            res_json["data"]["jobListings"]["paginationCursors"], page_num + 1
        )
    
    def _get_csrf_token(self):
        """
        Fetches csrf token needed for API by visiting a generic page
        """
        res = self.session.get(f"{self.base_url}/Job/computer-science-jobs.htm")
        pattern = r'"token":\s*"([^"]+)"'
        matches = re.findall(pattern, res.text)
        token = None
        if matches:
            token = matches[0]
        return token

    def _process_job(self, job_data):
        """
        Processes a single job and fetches its description.
        """
        job_id = job_data["jobview"]["job"]["listingId"]
        job_url = f"{self.base_url}job-listing/j?jl={job_id}"
        if job_url in self.seen_urls:
            return None
        self.seen_urls.add(job_url)
        job = job_data["jobview"]
        title = job["job"]["jobTitleText"]
        company_name = job["header"]["employerNameFromSearch"]
        company_id = job_data["jobview"]["header"]["employer"]["id"]
        location_name = job["header"].get("locationName", "")
        location_type = job["header"].get("locationType", "")
        age_in_days = job["header"].get("ageInDays")
        is_remote, location = False, None
        date_diff = (datetime.now() - timedelta(days=age_in_days)).date()
        date_posted = date_diff if age_in_days is not None else None

        if location_type == "S":
            is_remote = True
        else:
            location = parse_location(location_name)

        compensation = parse_compensation(job["header"])
        try:
            description = self._fetch_job_description(job_id)
        except:
            description = None
        company_url = f"{self.base_url}Overview/W-EI_IE{company_id}.htm"
        company_logo = (
            job_data["jobview"].get("overview", {}).get("squareLogoUrl", None)
        )
        listing_type = (
            job_data["jobview"]
            .get("header", {})
            .get("adOrderSponsorshipLevel", "")
            .lower()
        )
        return JobPost(
            id=f"gd-{job_id}",
            title=title,
            company_url=company_url if company_id else None,
            company_name=company_name,
            date_posted=date_posted,
            job_url=job_url,
            location=location,
            compensation=compensation,
            is_remote=is_remote,
            description=description,
            emails=extract_emails_from_text(description) if description else None,
            company_logo=company_logo,
            listing_type=listing_type,
        )

    def _fetch_job_description(self, job_id):
        """
        Fetches the job description for a single job ID.
        """
        url = f"{self.base_url}/graph"
        body = [
            {
                "operationName": "JobDetailQuery",
                "variables": {
                    "jl": job_id,
                    "queryString": "q",
                    "pageTypeEnum": "SERP",
                },
                "query": """
                query JobDetailQuery($jl: Long!, $queryString: String, $pageTypeEnum: PageTypeEnum) {
                    jobview: jobView(
                        listingId: $jl
                        contextHolder: {queryString: $queryString, pageTypeEnum: $pageTypeEnum}
                    ) {
                        job {
                            description
                            __typename
                        }
                        __typename
                    }
                }
                """,
            }
        ]
        res = requests.post(url, json=body, headers=headers)
        if res.status_code != 200:
            return None
        data = res.json()[0]
        desc = data["data"]["jobview"]["job"]["description"]
        if self.scraper_input.description_format == DescriptionFormat.MARKDOWN:
            desc = markdown_converter(desc)
        return desc


# Known Glassdoor location IDs — bypasses the blocked location lookup endpoint
    

    def _get_location(self, location: str, is_remote: bool) -> tuple:
        if not location or is_remote:
            return "11047", "STATE"

        # Check hardcoded map first — bypasses Cloudflare-blocked endpoint
        key = location.strip().lower()
        if key in KNOWN_LOCATIONS:
            loc_id, loc_type = KNOWN_LOCATIONS[key]
            log.info(f"Glassdoor: using known location id={loc_id}, type={loc_type} for '{location}'")
            return loc_id, loc_type

        # Try partial match (e.g. "Bangalore, India" -> "bangalore")
        for known_key, (loc_id, loc_type) in KNOWN_LOCATIONS.items():
            if known_key in key:
                log.info(f"Glassdoor: partial match '{known_key}' -> id={loc_id}, type={loc_type}")
                return loc_id, loc_type

        # Fallback: try the live endpoint (may be blocked)
        url = f"{self.base_url}/findPopularLocationAjax.htm?maxLocationsToReturn=10&term={location}"
        try:
            res = self.session.get(url, timeout=10)
            if res.status_code == 200:
                items = res.json()
                if items:
                    raw_type = items[0]["locationType"]
                    loc_type = {"C": "CITY", "S": "STATE", "N": "COUNTRY"}.get(raw_type, raw_type)
                    return int(items[0]["locationId"]), loc_type
        except Exception as e:
            log.warning(f"Glassdoor live location lookup failed: {e}")

        log.error(f"Glassdoor: could not resolve location '{location}'")
        return None, None

    def _add_payload(self, location_id, location_type, page_num, cursor=None):
        fromage = None
        if self.scraper_input.hours_old:
            fromage = max(self.scraper_input.hours_old // 24, 1)

        filter_params = []
        if self.scraper_input.easy_apply:
            filter_params.append({"filterKey": "applicationType", "values": "1"})
        if fromage:
            filter_params.append({"filterKey": "fromAge", "values": str(fromage)})

        # ✅ Correct Glassdoor location type codes
        type_code_map = {
            "CITY":    "IC",
            "STATE":   "IS",
            "COUNTRY": "IN",
            "METRO":   "IM",
        }
        type_code = type_code_map.get(location_type, "IC")

        payload = {
            "operationName": "JobSearchResultsQuery",
            "variables": {
                "excludeJobListingIds": [],
                "filterParams":        filter_params,
                "keyword":             self.scraper_input.search_term,
                "numJobsToShow":       30,
                "locationType":        location_type,
                "locationId":          int(location_id),
                "parameterUrlInput":   f"IL.0,12_{type_code}{location_id}",  # ✅ fixed
                "pageNumber":          page_num,
                "pageCursor":          cursor,
                "fromage":             fromage,
                "sort":                "date",
            },
            "query": query_template,
        }
        if self.scraper_input.job_type:
            payload["variables"]["filterParams"].append(
                {"filterKey": "jobType", "values": self.scraper_input.job_type.value[0]}
            )
        return json.dumps([payload])