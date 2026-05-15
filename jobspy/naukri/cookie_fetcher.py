from playwright.sync_api import sync_playwright

def get_naukri_headers() -> dict:
    """
    Intercepts the real API request headers from Naukri's own frontend.
    Returns headers including the dynamic Nkparam token.
    """
    captured_headers = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,  # visible so JS runs fully
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )

        page = context.new_page()

        # Intercept requests going to the Naukri job search API
        def handle_request(request):
            if "jobapi" in request.url and "search" in request.url:
                captured_headers.update(dict(request.headers))
                print(f"\n[+] Captured API request to: {request.url}")

        page.on("request", handle_request)

        # Go to a search page that triggers the API call
        page.goto(
            "https://www.naukri.com/software-engineer-jobs",
            wait_until="networkidle",
            timeout=40000
        )
        page.wait_for_timeout(5000)

        browser.close()

    return captured_headers