import csv
import gzip
import io
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import requests
import streamlit as st

st.set_page_config(page_title="Auto-Sitemap URL Checker", layout="wide")
st.title("🔎 Auto-Discover Sitemap & URL Checker")
st.write("Enter a target webpage URL, and the app will automatically find its domain's sitemap and check if the page is listed.")

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Streamlit Sitemap Checker'}

def discover_sitemap_urls(target_url):
    """Find sitemap location(s) via robots.txt or standard paths."""
    parsed = urlparse(target_url)
    domain_base = f"{parsed.scheme}://{parsed.netloc}"
    discovered_sitemaps = []

    # 1. Try reading robots.txt for Sitemap directives
    robots_url = f"{domain_base}/robots.txt"
    try:
        res = requests.get(robots_url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            matches = re.findall(r"(?i)^Sitemap:\s*(https?://[^\s]+)", res.text, re.MULTILINE)
            discovered_sitemaps.extend(matches)
    except Exception:
        pass

    # 2. Fallback: check standard sitemap paths if robots.txt has none
    if not discovered_sitemaps:
        fallback_paths = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-index.xml"]
        for path in fallback_paths:
            candidate = f"{domain_base}{path}"
            try:
                res = requests.head(candidate, headers=HEADERS, timeout=5)
                if res.status_code == 200:
                    discovered_sitemaps.append(candidate)
                    break
            except Exception:
                pass

    return list(set(discovered_sitemaps))

def fetch_sitemap_content(sitemap_url):
    """Fetch content and handle gzipped sitemaps."""
    try:
        response = requests.get(sitemap_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        if sitemap_url.endswith('.gz') or response.content[:2] == b'\x1f\x8b':
            return gzip.decompress(response.content)
        return response.content
    except Exception:
        return None

def parse_single_sitemap(sitemap_url):
    """Parse one XML sitemap for links and sub-sitemaps."""
    content = fetch_sitemap_content(sitemap_url)
    if not content:
        return set(), set()
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
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

def extract_all_urls_parallel(root_sitemap_urls, max_workers=10):
    """Recursively process all child sitemaps in parallel."""
    all_pages = set()
    visited_sitemaps = set()
    sitemaps_to_crawl = set(root_sitemap_urls)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while sitemaps_to_crawl:
            current_batch = sitemaps_to_crawl - visited_sitemaps
            if not current_batch:
                break
            visited_sitemaps.update(current_batch)

            future_to_url = {
                executor.submit(parse_single_sitemap, url): url for url in current_batch
            }
            sitemaps_to_crawl = set()

            for future in as_completed(future_to_url):
                pages, sub_sitemaps = future.result()
                all_pages.update(pages)
                sitemaps_to_crawl.update(sub_sitemaps)

    return all_pages

# User Input Form
target_input = st.text_input("Target URL to check", placeholder="https://example.com/blog/my-post")

if st.button("Auto-Discover Sitemap & Check") and target_input:
    clean_target = target_input.strip()

    with st.spinner("Finding sitemap location(s) from target domain..."):
        sitemap_sources = discover_sitemap_urls(clean_target)

    if not sitemap_sources:
        st.error("Could not auto-discover a sitemap via robots.txt or standard paths for this domain.")
    else:
        st.info(f"Discovered Sitemap Source(s): `{', '.join(sitemap_sources)}`")

        with st.spinner("Crawling sitemap index and sub-sitemaps in parallel..."):
            all_sitemap_urls = extract_all_urls_parallel(sitemap_sources)

        normalized_target = clean_target.rstrip('/')
        is_present = normalized_target in all_sitemap_urls

        st.subheader("Result")
        if is_present:
            st.success(f"**STATUS: Present**\n\nThe URL `{clean_target}` was found in the sitemap.")
        else:
            st.error(f"**STATUS: Not Present**\n\nThe URL `{clean_target}` was NOT found in the sitemap.")

        st.caption(f"Scanned {len(all_sitemap_urls)} total URLs across all discovered sitemaps.")
