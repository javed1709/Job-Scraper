import time
import random
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import json

# Constants
BASE_URL = "https://www.linkedin.com"
DELAY = 3
BAND_DELAY = 4
MAX_RETRIES = 5
RETRY_DELAY = 60
JOBS_PER_PAGE = 25
JSON_FILE_PATH = "jobs_data.json"

# Helper functions
def currency_parser(value):
    # Placeholder for currency parsing logic
    return value

def markdown_converter(text):
    # Placeholder for markdown conversion logic
    return text

def extract_emails_from_text(text):
    # Placeholder for email extraction logic
    return []

def get_location(metadata_card):
    location_tag = metadata_card.find("span", class_="job-search-card__location")
    return location_tag.get_text(strip=True) if location_tag else "N/A"

def process_job(job_card, job_id, full_descr, session):
    salary_tag = job_card.find("span", class_="job-search-card__salary-info")
    compensation = None
    if salary_tag:
        salary_text = salary_tag.get_text(separator=" ").strip()
        salary_values = [currency_parser(value) for value in salary_text.split("-")]
        salary_min = salary_values[0]
        salary_max = salary_values[1]
        currency = salary_text[0] if salary_text[0] != "$" else "USD"
        compensation = {
            "min_amount": int(salary_min),
            "max_amount": int(salary_max),
            "currency": currency,
        }

    title_tag = job_card.find("span", class_="sr-only")
    title = title_tag.get_text(strip=True) if title_tag else "N/A"

    company_tag = job_card.find("h4", class_="base-search-card__subtitle")
    company_a_tag = company_tag.find("a") if company_tag else None
    company_url = (
        company_a_tag.get("href").split("?")[0]
        if company_a_tag and company_a_tag.has_attr("href")
        else ""
    )
    company = company_a_tag.get_text(strip=True) if company_a_tag else "N/A"

    metadata_card = job_card.find("div", class_="base-search-card__metadata")
    location = get_location(metadata_card)

    datetime_tag = (
        metadata_card.find("time", class_="job-search-card__listdate")
        if metadata_card
        else None
    )
    date_posted = None
    if datetime_tag and "datetime" in datetime_tag.attrs:
        datetime_str = datetime_tag["datetime"]
        try:
            date_posted = datetime.strptime(datetime_str, "%Y-%m-%d")
        except:
            date_posted = None

    job_details = {}
    if full_descr:
        job_details = get_job_details(job_id, session)

    return {
        "id": job_id,
        "title": title,
        "company_name": company,
        "company_url": company_url,
        "location": location,
        "date_posted": date_posted,
        "job_url": f"{BASE_URL}/jobs/view/{job_id}",
        "compensation": compensation,
        "description": job_details.get("description"),
        "logo_photo_url": job_details.get("logo_photo_url"),
        "job_function": job_details.get("job_function"),
    }

def get_job_details(job_id, session):
    try:
        response = session.get(f"{BASE_URL}/jobs/view/{job_id}", timeout=5)
        response.raise_for_status()
    except:
        return {}

    if "linkedin.com/signup" in response.url:
        return {}

    soup = BeautifulSoup(response.text, "html.parser")
    div_content = soup.find(
        "div", class_=lambda x: x and "show-more-less-html__markup" in x
    )
    description = None
    if div_content is not None:
        div_content = div_content.get_text(separator=" ")
        description = markdown_converter(div_content)
        description = description.replace("Read more", "")

    logo_tag = soup.find("img", class_="job-search-company__logo")
    logo_photo_url = logo_tag["src"] if logo_tag else ""

    return {
        "description": description,
        "logo_photo_url": logo_photo_url,
        "job_function": None
    }

def save_to_json(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# Main function
def scrape_jobs(search_term, location, distance, is_remote, job_type, easy_apply, company_ids, offset, results_wanted, hours_old):
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    })

    job_list = []
    seen_ids = set()
    page = offset // 10 * 10 if offset else 0
    seconds_old = hours_old * 3600 if hours_old else None
    continue_search = lambda: len(job_list) < results_wanted and page < 1000

    while continue_search():
        params = {
            "keywords": search_term,
            "location": location,
            "distance": distance,
            "f_WT": 2 if is_remote else None,
            "f_JT": job_type,
            "pageNum": 0,
            "start": page,
            "f_AL": "true" if easy_apply else None,
            "f_C": ",".join(map(str, company_ids)) if company_ids else None,
        }
        if seconds_old is not None:
            params["f_TPR"] = f"r{seconds_old}"

        params = {k: v for k, v in params.items() if v is not None}
        attempt = 0

        while attempt < MAX_RETRIES:
            try:
                response = session.get(f"{BASE_URL}/jobs-guest/jobs/api/seeMoreJobPostings/search?", params=params, timeout=10)
                if response.status_code == 429:
                    attempt += 1
                    wait_time = RETRY_DELAY * attempt
                    print(f"Rate limit hit. Waiting for {wait_time} seconds before retrying.")
                    time.sleep(wait_time)
                    continue
                elif response.status_code not in range(200, 400):
                    print(f"LinkedIn response status code {response.status_code}")
                    return job_list
                break
            except Exception as e:
                print(f"LinkedIn: {str(e)}")
                return job_list
        else:
            print("Max retries reached. Exiting.")
            return job_list

        soup = BeautifulSoup(response.text, "html.parser")
        job_cards = soup.find_all("div", class_="base-search-card")
        if len(job_cards) == 0:
            return job_list

        for job_card in job_cards:
            href_tag = job_card.find("a", class_="base-card__full-link")
            if href_tag and "href" in href_tag.attrs:
                href = href_tag.attrs["href"].split("?")[0]
                job_id = href.split("-")[-1]

                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                try:
                    job_post = process_job(job_card, job_id, full_descr=True, session=session)
                    if job_post:
                        job_list.append(job_post)
                    if not continue_search():
                        break
                except Exception as e:
                    print(f"Error processing job {job_id}: {str(e)}")

        if continue_search():
            time.sleep(random.uniform(DELAY, DELAY + BAND_DELAY))
            page += len(job_list)

    return job_list[:results_wanted]

# Example usage
if __name__ == "__main__":
    search_term = "Software Engineer"
    location = "Hyderabad"
    distance = "25"
    is_remote = False
    job_type = "full-time"
    easy_apply = True
    company_ids = []  # list of LinkedIn company IDs
    offset = 0
    results_wanted = 10
    hours_old = 24

    jobs = scrape_jobs(search_term, location, distance, is_remote, job_type, easy_apply, company_ids, offset, results_wanted, hours_old)
    save_to_json(jobs, JSON_FILE_PATH)
    print(f"Job data saved to {JSON_FILE_PATH}")
