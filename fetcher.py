
import requests
import yaml
import json
import os
import time

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
HEADERS = {"Accept": "application/vnd.github.v3+json"}

if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"


def is_ai_related(item, category, subcategory):
    """Identify potentially AI-related projects using landscape metadata."""
    text = " ".join([
        str(item.get("name", "")),
        str(item.get("description", "")),
        str(category.get("name", "")),
        str(subcategory.get("name", "")),
    ]).lower()

    keywords = [
        "artificial intelligence",
        "machine learning",
        "generative ai",
        "large language model",
        "large language models",
        "llm",
        "llms",
        "ai agent",
        "ai agents",
        "inference",
        "model training",
    ]

    return any(keyword in text for keyword in keywords)


def get_live_cncf_repos():
    """Fetch official CNCF projects and their landscape metadata."""
    print("Fetching CNCF landscape source directly from GitHub...")

    try:
        response = requests.get(
            "https://raw.githubusercontent.com/cncf/landscape/master/landscape.yml",
            timeout=30,
        )

        if response.status_code != 200:
            print(f"Failed to fetch YAML: {response.status_code}")
            return {}

        landscape_data = yaml.safe_load(response.text) or {}

    except Exception as e:
        print(f"Failed to fetch or parse landscape YAML: {e}")
        return {}

    repos = {}

    for category in landscape_data.get("landscape") or []:
        for subcategory in category.get("subcategories") or []:
            for item in subcategory.get("items") or []:
                project_tier = item.get("project")

                if project_tier not in ["graduated", "incubating", "sandbox"]:
                    continue

                repo_url = item.get("repo_url", "")

                if not (
                    isinstance(repo_url, str)
                    and repo_url.startswith("https://github.com/")
                ):
                    continue

                repo_path = (
                    repo_url.replace("https://github.com/", "")
                    .strip("/")
                    .removesuffix(".git")
                )

                if not repo_path:
                    continue

                repos[repo_path] = {
                    "tier": project_tier.capitalize(),
                    "lang": "Unknown",
                    "category": category.get("name", ""),
                    "subcategory": subcategory.get("name", ""),
                    "description": item.get("description", ""),
                    "ai_related": is_ai_related(
                        item, category, subcategory
                    ),
                }

    print(f"Discovered {len(repos)} official CNCF GitHub repositories.")
    print(
        f"Potentially AI-related repositories: "
        f"{sum(repo['ai_related'] for repo in repos.values())}"
    )

    return repos


def github_get(url, params=None, max_retries=3):
    """Request GitHub API data with retries for rate limits."""
    response = None

    for attempt in range(max_retries):
        try:
            response = requests.get(
                url,
                headers=HEADERS,
                params=params,
                timeout=30,
            )
        except requests.RequestException as e:
            print(f"Request error for {url}: {e}")

            if attempt < max_retries - 1:
                time.sleep(5 * (attempt + 1))
                continue

            return None

        if response.status_code == 200:
            return response

        if response.status_code in (403, 429):
            remaining = response.headers.get("X-RateLimit-Remaining")
            reset_ts = response.headers.get("X-RateLimit-Reset")

            if remaining == "0" and reset_ts:
                wait_seconds = max(
                    int(reset_ts) - int(time.time()), 1
                )
                wait_seconds = min(wait_seconds, 60)
            else:
                wait_seconds = 5 * (attempt + 1)

            print(
                f"Rate limited. Waiting {wait_seconds}s "
                f"(attempt {attempt + 1}/{max_retries})..."
            )
            time.sleep(wait_seconds)
            continue

        print(f"Request failed: {response.status_code} for {url}")
        return response

    print(f"Giving up on {url} after {max_retries} retries.")
    return response


def fetch_issues(repos):
    """Fetch beginner issues and attach repository metadata."""
    labels = ["good first issue", "good-first-issue", "help wanted"]
    all_issues = []
    seen_issue_urls = set()

    for repo, meta in repos.items():
        print(f"Checking {repo} ({meta['tier']})...")

        repo_res = github_get(f"https://api.github.com/repos/{repo}")

        if repo_res is not None and repo_res.status_code == 200:
            meta["lang"] = repo_res.json().get("language") or "Unknown"

        for label in labels:
            url = f"https://api.github.com/repos/{repo}/issues"
            params = {
                "state": "open",
                "labels": label,
                "per_page": 30,
            }

            response = github_get(url, params=params)

            if response is None or response.status_code != 200:
                continue

            issues = response.json()

            for issue in issues:
                if "pull_request" in issue:
                    continue

                issue_url = issue.get("html_url")

                if not issue_url or issue_url in seen_issue_urls:
                    continue

                issue_data = {
                    "repo": repo,
                    "tier": meta["tier"],
                    "lang": meta["lang"],
                    "category": meta.get("category", ""),
                    "subcategory": meta.get("subcategory", ""),
                    "description": meta.get("description", ""),
                    "ai_related": meta.get("ai_related", False),
                    "title": issue["title"],
                    "url": issue_url,
                    "labels": [
                        label_data["name"]
                        for label_data in issue.get("labels", [])
                    ],
                    "created_at": issue["created_at"],
                }

                all_issues.append(issue_data)
                seen_issue_urls.add(issue_url)

        time.sleep(0.5)

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(all_issues, f, indent=4, ensure_ascii=False)

    print("\n--- SUCCESS ---")
    print(f"Saved {len(all_issues)} total beginner issues to data.json")


if __name__ == "__main__":
    cncf_repos = get_live_cncf_repos()

    if cncf_repos:
        fetch_issues(cncf_repos)
    else:
        print("No repositories found to scan. Halting process.")
