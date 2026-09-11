import gzip
import io
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import matplotlib.pyplot as plt
import requests
import streamlit as st

st.set_page_config(page_title="Auto-Sitemap URL Checker", layout="wide")
st.title("🔎 Auto-Discover Sitemap & URL Checker")

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Streamlit Sitemap Checker'}

def discover_sitemap_urls(target_url):
    parsed = urlparse(target_url)
    domain_base = f"{parsed.scheme}://{parsed.netloc}"
    discovered_sitemaps = []

    robots_url = f"{domain_base}/robots.txt"
    try:
        res = requests.get(robots_url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            matches = re.findall(r"(?i)^Sitemap:\s*(https?://[^\s]+)", res.text, re.MULTILINE)
            discovered_sitemaps.extend(matches)
    except Exception:
        pass

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
    try:
        response = requests.get(sitemap_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        if sitemap_url.endswith('.gz') or response.content[:2] == b'\x1f\x8b':
            return gzip.decompress(response.content)
        return response.content
    except Exception:
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

def extract_all_urls_parallel(root_sitemap_urls, max_workers=10):
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

def generate_result_card(target_url, is_present, sitemap_sources, total_scanned):
    """Generates a styled result card PNG using Matplotlib in memory."""
    fig, ax = plt.subplots(figsize=(8, 4.5), dpi=200)
    
    # Hide standard plot axes
    ax.axis('off')
    
    # Card Background & Colors
    card_color = "#E8F5E9" if is_present else "#FFEBEE"
    status_text = "PRESENT IN SITEMAP" if is_present else "NOT PRESENT IN SITEMAP"
    status_color = "#2E7D32" if is_present else "#C62828"
    
    # Draw background box
    fig.patch.set_facecolor("#F8F9FA")
    ax.add_patch(plt.Rectangle((0.05, 0.05), 0.9, 0.9, color=card_color, ec="#B0BEC5", lw=1.5, transform=ax.transAxes, zorder=1))

    # Text Content
    ax.text(0.10, 0.80, "SITEMAP VERIFICATION REPORT", fontsize=10, fontweight='bold', color="#546E7A", transform=ax.transAxes)
    ax.text(0.10, 0.68, status_text, fontsize=16, fontweight='bold', color=status_color, transform=ax.transAxes)
    
    # Details
    truncated_target = target_url if len(target_url) <= 55 else target_url[:52] + "..."
    ax.text(0.10, 0.52, f"Target URL:\n{truncated_target}", fontsize=9, color="#263238", transform=ax.transAxes)
    
    sources_str = ", ".join(sitemap_sources)
    truncated_sources = sources_str if len(sources_str) <= 55 else sources_str[:52] + "..."
    ax.text(0.10, 0.35, f"Discovered Sitemap(s):\n{truncated_sources}", fontsize=8, color="#37474F", transform=ax.transAxes)
    
    ax.text(0.10, 0.18, f"Total Sitemap URLs Scanned: {total_scanned:,}", fontsize=9, fontweight='bold', color="#37474F", transform=ax.transAxes)

    # Save to BytesIO buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf

# User UI
target_input = st.text_input("Target URL to check", placeholder="https://example.com/blog/my-post")

if st.button("Auto-Discover Sitemap & Check") and target_input:
    clean_target = target_input.strip()

    with st.spinner("Finding sitemap location(s)..."):
        sitemap_sources = discover_sitemap_urls(clean_target)

    if not sitemap_sources:
        st.error("Could not auto-discover a sitemap via robots.txt or standard paths.")
    else:
        st.info(f"Discovered Sitemap Source(s): `{', '.join(sitemap_sources)}`")

        with st.spinner("Crawling sitemap index in parallel..."):
            all_sitemap_urls = extract_all_urls_parallel(sitemap_sources)

        normalized_target = clean_target.rstrip('/')
        is_present = normalized_target in all_sitemap_urls

        st.subheader("Result")
        if is_present:
            st.success(f"**STATUS: Present**\n\nThe URL `{clean_target}` was found in the sitemap.")
        else:
            st.error(f"**STATUS: Not Present**\n\nThe URL `{clean_target}` was NOT found in the sitemap.")

        # Generate image snapshot in memory
        img_buffer = generate_result_card(clean_target, is_present, sitemap_sources, len(all_sitemap_urls))

        # Preview & Download
        st.image(img_buffer, caption="Generated Report Image Preview", width=550)
        
        st.download_button(
            label="📸 Download Result Image (.png)",
            data=img_buffer,
            file_name="sitemap_check_result.png",
            mime="image/png"
        )
