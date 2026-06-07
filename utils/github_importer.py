import requests
import logging
from agents.api_client import RotatingOllamaClient

logger = logging.getLogger(__name__)

class GitHubProjectImporter:
    def __init__(self, client: RotatingOllamaClient, github_token: str = None):
        self.client = client
        self.github_token = github_token
        self.headers = {"Accept": "application/vnd.github.v3+json"}
        if self.github_token:
            self.headers["Authorization"] = f"token {self.github_token}"

    def _extract_username(self, github_url: str) -> str:
        """Extracts username from a GitHub URL or handle."""
        if not github_url:
            return ""
        # Remove trailing slash
        url = github_url.rstrip("/")
        if "github.com/" in url:
            parts = url.split("github.com/")[-1].split("/")
            return parts[0]
        return url.strip()

    def fetch_repo_data(self, repo_url: str) -> dict:
        """
        Fetches data from a GitHub repository URL.
        Example URL: https://github.com/username/repo
        """
        try:
            # Extract owner and repo name
            parts = repo_url.rstrip("/").split("/")
            if len(parts) < 2:
                raise ValueError("Invalid GitHub URL")

            owner = parts[-2]
            repo = parts[-1]

            # 1. Get general repo info
            info_url = f"https://api.github.com/repos/{owner}/{repo}"
            resp = requests.get(info_url, headers=self.headers)
            resp.raise_for_status()
            data = resp.json()

            # 2. Get languages
            lang_url = f"https://api.github.com/repos/{owner}/{repo}/languages"
            lang_resp = requests.get(lang_url, headers=self.headers)
            lang_resp.raise_for_status()
            langs = list(lang_resp.json().keys())

            # 3. Get README
            readme_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
            readme_resp = requests.get(readme_url, headers=self.headers)
            readme_content = ""
            if readme_resp.status_code == 200:
                # GitHub returns README as base64 encoded
                import base64
                readme_encoded = readme_resp.json().get("content", "")
                readme_content = base64.b64decode(readme_encoded).decode("utf-8", errors="ignore")

            return {
                "name": data.get("name", "Unknown Project"),
                "description": data.get("description", "No description provided."),
                "languages": langs,
                "stars": data.get("stargazers_count", 0),
                "readme": readme_content,
                "url": repo_url
            }
        except Exception as e:
            logger.error(f"Failed to fetch GitHub repo data: {e}")
            raise e

    def generate_project_entry(self, repo_url: str) -> str:
        """
        Fetches repo data and uses AI to generate a resume-ready project entry.
        """
        data = self.fetch_repo_data(repo_url)

        prompt = f"""
        You are an expert resume writer. I will provide you with raw data from a GitHub repository.
        Your task is to convert this into a professional project entry for a resume.

        REPO DATA:
        - Name: {data['name']}
        - Description: {data['description']}
        - Languages: {', '.join(data['languages'])}
        - Stars: {data['stars']}
        - URL: {data['url']}
        - README:
        {data['readme'][:3000]} # Truncate to avoid token limits

        OUTPUT FORMAT:
        Project Name | Tech Stack | {data['url']}
        - Bullet 1: (Problem solved, key technology, and a measurable metric)
        - Bullet 2: (Technical implementation detail, a specific tool used, and a result)
        - Bullet 3: (Overall impact, scale, or a specific achievement)

        RULES:
        - Do NOT use LaTeX tags.
        - Use a professional, action-oriented tone.
        - Every bullet MUST include a believable metric (%, time, count, etc.).
        - Use the languages listed in the repo data for the Tech Stack.
        - Return ONLY the formatted project entry. No introduction.
        """

        result = self.client.complete(
            system="You are a professional resume builder. Convert raw GitHub data into high-impact resume bullet points.",
            user=prompt
        )
        return result.strip()

    def import_user_projects(self, github_url: str):
        """
        Fetches all public repositories for a user and generates resume entries for each.
        Yields entries as they are generated.
        """
        username = self._extract_username(github_url)
        if not username:
            raise ValueError("Could not extract GitHub username from profile.")

        # 1. Fetch all repos for the user
        repos_url = f"https://api.github.com/users/{username}/repos"
        params = {"per_page": 100, "type": "owner", "sort": "updated"}
        resp = requests.get(repos_url, params=params)
        resp.raise_for_status()
        repos_data = resp.json()

        # Yield the total count first so the UI can show progress
        # We'll use a special format or the caller can just know the list length
        # But we are a generator, so we can't easily yield the length AND items
        # unless we return (total, generator).

        # For simplicity, I'll return the list of repo data first, or just
        # let the caller handle the list.
        # Actually, let's just yield (repo_name, entry) tuples.

        for repo in repos_data:
            # Skip forks and very small/empty repos to keep quality high
            if repo.get("forks_count", 0) > 0 and repo.get("fork", False):
                continue

            repo_url = repo["html_url"]
            try:
                logger.info(f"Importing project: {repo['name']} from {repo_url}")
                entry = self.generate_project_entry(repo_url)
                yield repo["name"], entry
            except Exception as e:
                logger.warning(f"Failed to import {repo['name']}: {e}")
                yield repo["name"], None
