import csv
import gzip
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests


def fetch_sitemap_content(sitemap_url):
    """Fetch sitemap content safely with timeout and error handling."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python Multithreaded Sitemap Checker'
    }

    try:
        response = requests.get(sitemap_url, headers=headers, timeout=15)
        response.raise_for_status()

        if sitemap_url.endswith('.gz') or response.content[:2] == b'\x1f\x8b':
            return gzip.decompress(response.content)
        return response.content
    except requests.RequestException as e:
        print(f"  [Error] Failed fetching {sitemap_url}: {e}")
        return None


def parse_single_sitemap(sitemap_url):
    """Fetch and parse one sitemap file; returns page URLs and sub-sitemap URLs."""
    content = fetch_sitemap_content(sitemap_url)
    if not content:
        return set(), set()

    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        print(f"  [Error] XML Parsing Error in {sitemap_url}: {e}")
        return set(), set()

    found_pages = set()
    found_sub_sitemaps = set()

    for elem in root.iter():
        tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag
        if tag == 'loc' and elem.text:
            text = elem.text.strip()
            if text.endswith('.xml') or text.endswith('.xml.gz'):
                found_sub_sitemaps.add(text)
            else:
                found_pages.add(text.rstrip('/'))

    return found_pages, found_sub_sitemaps


def extract_all_urls_parallel(root_sitemap_url, max_workers=10):
    """Crawl sitemaps in parallel using thread pools."""
    all_pages = set()
    visited_sitemaps = set()
    sitemaps_to_crawl = {root_sitemap_url}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while sitemaps_to_crawl:
            # Queue only unvisited sitemaps
            current_batch = sitemaps_to_crawl - visited_sitemaps
            if not current_batch:
                break

            visited_sitemaps.update(current_batch)
            print(f"Crawling batch of {len(current_batch)} sitemap(s) using up to {max_workers} threads...")

            # Submit current batch to the thread pool
            future_to_url = {
                executor.submit(parse_single_sitemap, url): url for url in current_batch
            }

            sitemaps_to_crawl = set()

            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    pages, sub_sitemaps = future.result()
                    all_pages.update(pages)
                    # Add newly discovered sub-sitemaps for the next round
                    sitemaps_to_crawl.update(sub_sitemaps)
                except Exception as exc:
                    print(f"  [Exception] {url} generated an error: {exc}")

    return all_pages


def batch_check_urls(sitemap_url, target_urls_file, output_csv, max_workers=10):
    """Load target URLs, gather all sitemap links in parallel, and export CSV."""
    try:
        with open(target_urls_file, 'r', encoding='utf-8') as f:
            target_urls = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"Error: Input file '{target_urls_file}' not found.")
        return

    if not target_urls:
        print("Error: Input URL file is empty.")
        return

    print(f"\nLoaded {len(target_urls)} target URLs to check.")
    print("\n--- Starting Multithreaded Crawl ---")

    sitemap_urls_set = extract_all_urls_parallel(sitemap_url, max_workers=max_workers)
    print(f"\nFinished crawling! Total unique page URLs collected: {len(sitemap_urls_set)}")

    print(f"\nWriting results to '{output_csv}'...")
    present_count = 0

    with open(output_csv, mode='w', newline='', encoding='utf-8') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(['Target URL', 'Status'])

        for target in target_urls:
            normalized_target = target.rstrip('/')
            if normalized_target in sitemap_urls_set:
                status = "Present"
                present_count += 1
            else:
                status = "Not Present"

            writer.writerow([target, status])

    print("\n--- Summary ---")
    print(f"Total checked: {len(target_urls)}")
    print(f"Present: {present_count}")
    print(f"Not Present: {len(target_urls) - present_count}")
    print(f"Results saved to: {output_csv}")


if __name__ == "__main__":
    print("--- Multithreaded Sitemap URL Checker ---")
    sitemap_input = input("Enter Root Sitemap URL: ").strip()
    file_input = input("Enter path to target URLs file (e.g., urls.txt): ").strip()
    csv_output = input("Enter output CSV file name (default: results.csv): ").strip() or "results.csv"
    threads_input = input("Enter max worker threads (default: 10): ").strip()

    max_threads = int(threads_input) if threads_input.isdigit() else 10

    if sitemap_input and file_input:
        batch_check_urls(sitemap_input, file_input, csv_output, max_workers=max_threads)
    else:
        print("Error: Sitemap URL and Target File Path are required.")
