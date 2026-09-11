import csv
import gzip
import io
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import streamlit as st

st.set_page_config(page_title="Sitemap Checker", layout="wide")
st.title("🌐 Multithreaded Sitemap URL Checker")

def fetch_sitemap_content(sitemap_url):
    headers = {'User-Agent': 'Mozilla/5.0 Streamlit Sitemap Checker'}
    try:
        response = requests.get(sitemap_url, headers=headers, timeout=15)
        response.raise_for_status()
        if sitemap_url.endswith('.gz') or response.content[:2] == b'\x1f\x8b':
            return gzip.decompress(response.content)
        return response.content
    except Exception as e:
        return None

def parse_single_sitemap(sitemap_url):
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

def extract_all_urls_parallel(root_sitemap_url, max_workers=10):
    all_pages = set()
    visited_sitemaps = set()
    sitemaps_to_crawl = {root_sitemap_url}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        while sitemaps_to_crawl:
            current_batch = sitemaps_to_crawl - visited_sitemaps
            if not current_batch:
                break
            visited_sitemaps.update(current_batch)
            future_to_url = {executor.submit(parse_single_sitemap, url): url for url in current_batch}
            sitemaps_to_crawl = set()

            for future in as_completed(future_to_url):
                pages, sub_sitemaps = future.result()
                all_pages.update(pages)
                sitemaps_to_crawl.update(sub_sitemaps)

    return all_pages

# Web Form UI
sitemap_url = st.text_input("Root Sitemap URL", "https://example.com/sitemap.xml")
uploaded_file = st.file_uploader("Upload target URLs text file (.txt)", type=["txt"])
max_threads = st.slider("Max Worker Threads", 1, 20, 10)

if st.button("Run Check") and sitemap_url and uploaded_file:
    target_urls = [line.decode("utf-8").strip() for line in uploaded_file if line.decode("utf-8").strip()]
    
    with st.spinner("Crawling sitemaps..."):
        sitemap_urls_set = extract_all_urls_parallel(sitemap_url, max_workers=max_threads)

    results = []
    present_count = 0
    for target in target_urls:
        status = "Present" if target.rstrip('/') in sitemap_urls_set else "Not Present"
        if status == "Present":
            present_count += 1
        results.append({"Target URL": target, "Status": status})

    st.success(f"Checked {len(target_urls)} URLs. Found {present_count} present.")
    st.dataframe(results)

    # Downloadable CSV Buffer
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["Target URL", "Status"])
    writer.writeheader()
    writer.writerows(results)
    
    st.download_button(
        label="Download Results CSV",
        data=output.getvalue(),
        file_name="sitemap_check_results.csv",
        mime="text/csv"
    )
