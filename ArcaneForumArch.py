#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║          ✦ ARCANE FORUM ARCHIVER ✦                       ║
║     vBulletin Backup & Converter — Mystical Edition      ║
╚══════════════════════════════════════════════════════════╝
"""

import os
import re
import time
import json
import gc
import base64
import mimetypes
import threading
import multiprocessing as mp
from datetime import datetime
from urllib.parse import urljoin, urlparse, urldefrag
from queue import Queue

import requests
from bs4 import BeautifulSoup

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont

# ─────────────────────────────────────────────
#  COLORS & ESOTERIC THEME
# ─────────────────────────────────────────────
BG_DEEP     = "#0a0612"
BG_MID      = "#110d1e"
BG_PANEL    = "#16102a"
ACCENT_GOLD = "#c9a84c"
ACCENT_PURP = "#7b4fa6"
ACCENT_TEAL = "#3ecfcf"
RUNE_RED    = "#c0392b"
TEXT_MAIN   = "#e8dfc8"
TEXT_DIM    = "#7a6f8a"
BORDER_GLOW = "#3d2a6e"

RUNE_SYMBOLS = ["᛭","ᚠ","ᚢ","ᚦ","ᚨ","ᚱ","ᚲ","ᚷ","ᚹ","ᚺ","ᚾ","ᛁ","ᛃ","ᛇ",
                "ᛈ","ᛉ","ᛊ","ᛏ","ᛒ","ᛖ","ᛗ","ᛚ","ᛜ","ᛞ","ᛟ"]

# Extensions we treat as downloadable media
IMAGE_EXTS = {'.jpg','.jpeg','.png','.gif','.webp','.bmp','.svg','.tiff','.avif'}
VIDEO_EXTS = {'.mp4','.webm','.mov','.avi','.mkv','.ogv','.flv','.m4v'}
AUDIO_EXTS = {'.mp3','.ogg','.wav','.aac','.flac','.m4a','.opus'}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS | AUDIO_EXTS

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def clean_text(text):
    return ' '.join(text.strip().replace('\r','').replace('\xa0',' ').split())

def parse_date(text):
    try:
        return datetime.strptime(text, '%b %d, %Y at %I:%M %p')
    except:
        return None

def safe_filename(name, maxlen=80):
    return re.sub(r'[<>:"/\\|?*\n\r\t]', '_', name)[:maxlen]

def get_ext(url):
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext.lower()

def guess_mime(url, data=None):
    ext = get_ext(url)
    mime = mimetypes.guess_type('file' + ext)[0]
    if mime:
        return mime
    # fallback by sniffing first bytes
    if data and len(data) >= 4:
        sig = data[:4]
        if sig[:3] == b'\xff\xd8\xff':   return 'image/jpeg'
        if sig[:4] == b'\x89PNG':         return 'image/png'
        if sig[:6] in (b'GIF87a',b'GIF89a'[:4]): return 'image/gif'
        if sig[:4] == b'RIFF':           return 'video/webm'
    return 'application/octet-stream'

def data_uri(data_bytes, mime):
    b64 = base64.b64encode(data_bytes).decode('ascii')
    return f"data:{mime};base64,{b64}"

# ─────────────────────────────────────────────
#  MEDIA DOWNLOADER
# ─────────────────────────────────────────────

class MediaDownloader:
    """Downloads media files referenced in HTML pages and saves them to a subfolder."""

    def __init__(self, output_dir, delay=0.3, log_callback=None, stop_event=None):
        self.media_dir   = os.path.join(output_dir, 'media')
        self.delay       = delay
        self.log         = log_callback or print
        self._stop       = stop_event or threading.Event()
        self._index_file = os.path.join(self.media_dir, '_media_index.json')
        os.makedirs(self.media_dir, exist_ok=True)
        self._index = self._load_index()

    def _load_index(self):
        if os.path.exists(self._index_file):
            try:
                with open(self._index_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}

    def _save_index(self):
        try:
            with open(self._index_file, 'w', encoding='utf-8') as f:
                json.dump(self._index, f, indent=2, ensure_ascii=False)
        except:
            pass

    def _fetch_bytes(self, url):
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            r = requests.get(url, headers=headers, timeout=20, stream=True)
            r.raise_for_status()
            chunks = []
            for chunk in r.iter_content(65536):
                if self._stop.is_set():
                    return None
                chunks.append(chunk)
            return b''.join(chunks)
        except Exception as e:
            self.log(f"    ⚠ Media skip ({os.path.basename(urlparse(url).path)}): {e}")
            return None

    def download_from_html(self, html_content, page_base_url):
        """Extract all media URLs from html_content and download them. Returns count."""
        soup = BeautifulSoup(html_content, 'html.parser')
        urls = set()

        # img src
        for tag in soup.find_all('img', src=True):
            urls.add(urljoin(page_base_url, tag['src']))
        # video / audio src and source children
        for tag in soup.find_all(['video','audio'], src=True):
            urls.add(urljoin(page_base_url, tag['src']))
        for tag in soup.find_all('source', src=True):
            urls.add(urljoin(page_base_url, tag['src']))
        # a href pointing to media
        for tag in soup.find_all('a', href=True):
            href = urljoin(page_base_url, tag['href'])
            if get_ext(href) in MEDIA_EXTS:
                urls.add(href)
        # data-src (lazy loading)
        for tag in soup.find_all(attrs={'data-src': True}):
            urls.add(urljoin(page_base_url, tag['data-src']))

        soup.decompose()

        # filter to only media extensions (skip tracker pixels etc that lack ext)
        media_urls = [u for u in urls if get_ext(u) in MEDIA_EXTS and urlparse(u).scheme in ('http','https')]

        downloaded = 0
        for url in media_urls:
            if self._stop.is_set():
                break
            if url in self._index:
                continue
            data = self._fetch_bytes(url)
            if data is None:
                continue
            ext  = get_ext(url) or '.bin'
            fname = safe_filename(os.path.basename(urlparse(url).path) or 'media', 120)
            if not fname.lower().endswith(ext):
                fname += ext
            # avoid collisions
            fpath = os.path.join(self.media_dir, fname)
            counter = 1
            while os.path.exists(fpath):
                base, e = os.path.splitext(fname)
                fpath = os.path.join(self.media_dir, f"{base}_{counter}{e}")
                counter += 1
            try:
                with open(fpath, 'wb') as f:
                    f.write(data)
                self._index[url] = os.path.basename(fpath)
                downloaded += 1
                self.log(f"    📥 Media: {os.path.basename(fpath)}")
                time.sleep(self.delay)
            except Exception as e:
                self.log(f"    ⚠ Could not save media: {e}")

        self._save_index()
        return downloaded

    def get_local_path(self, url):
        """Return local filename for a previously-downloaded URL, or None."""
        fname = self._index.get(url)
        if fname:
            return os.path.join(self.media_dir, fname)
        return None

    def get_base64_uri(self, url):
        """Return data: URI for a previously-downloaded URL, or None."""
        path = self.get_local_path(url)
        if path and os.path.exists(path):
            try:
                with open(path, 'rb') as f:
                    data = f.read()
                mime = guess_mime(url, data)
                return data_uri(data, mime)
            except:
                pass
        return None


# ─────────────────────────────────────────────
#  BACKUP LOGIC (original, unchanged)
# ─────────────────────────────────────────────

class VBulletinBackup:
    def __init__(self, base_url, output_dir="backup", delay=1.0, max_workers=10,
                 start_page=1, log_callback=None, download_media=False, stop_event=None):
        self.base_url       = base_url.rstrip('/')
        self.output_dir     = output_dir
        self.delay          = delay
        self.max_workers    = max_workers
        self.start_page     = start_page
        self.log            = log_callback or print
        self.download_media = download_media
        os.makedirs(output_dir, exist_ok=True)
        self.metadata_file  = os.path.join(output_dir, 'backup_metadata.json')
        self.metadata       = self.load_metadata()
        self._stop_event    = stop_event or threading.Event()
        self._media_dl      = MediaDownloader(output_dir, delay=delay*0.5,
                                              log_callback=log_callback,
                                              stop_event=self._stop_event) if download_media else None
        self.force_gc()

    def force_gc(self):
        for _ in range(3): gc.collect()

    def load_metadata(self):
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file,'r',encoding='utf-8') as f:
                    return json.load(f)
            except: pass
        return {'threads':{},'last_backup':None,'total_threads':0,'completed_threads':0}

    def save_metadata(self):
        self.metadata['last_backup'] = datetime.now().isoformat()
        with open(self.metadata_file,'w',encoding='utf-8') as f:
            json.dump(self.metadata, f, indent=2, ensure_ascii=False)
        self.force_gc()

    def get_page(self, url):
        session = response = None
        try:
            session = requests.Session()
            session.headers.update({'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
            response = session.get(url, timeout=30, stream=True)
            response.raise_for_status()
            content = ""
            for chunk in response.iter_content(chunk_size=8192, decode_unicode=True):
                if chunk: content += chunk
            return content
        except Exception as e:
            self.log(f"  ⚠ Error downloading {url}: {e}")
            return None
        finally:
            if response: response.close(); del response
            if session:  session.close();  del session
            self.force_gc()

    def extract_thread_links(self, html_content, base_url):
        thread_links = []
        soup = None
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            for pattern in ['a[href*="showthread.php"]','a[href*="/threads/"]','a[href*="viewtopic.php"]']:
                for link in soup.select(pattern):
                    href = link.get('href')
                    if href:
                        full_url  = urljoin(base_url, href)
                        thread_id = self.extract_thread_id(full_url)
                        if thread_id:
                            thread_links.append({'id':thread_id,'url':full_url,'title':link.get_text(strip=True)})
        finally:
            if soup: soup.decompose(); del soup
            del html_content
            self.force_gc()
        seen, unique = set(), []
        for t in thread_links:
            if t['id'] not in seen:
                seen.add(t['id']); unique.append(t)
        return unique

    def extract_thread_id(self, url):
        for p in [r'showthread\.php.*[?&]t=(\d+)',r'/threads/[^/]*\.(\d+)',r'viewtopic\.php.*[?&]t=(\d+)']:
            m = re.search(p, url)
            if m: return m.group(1)
        return None

    def get_all_pages_urls(self, section_url):
        pages = [section_url]
        html_content = soup = None
        try:
            html_content = self.get_page(section_url)
            if not html_content: return pages
            soup = BeautifulSoup(html_content, 'html.parser')
            page_numbers = set()
            for link in soup.find_all("a", href=True):
                m = re.search(r'(?:[?&]page=|/page-)(\d+)', link["href"])
                if m: page_numbers.add(int(m.group(1)))
            if page_numbers:
                for page_num in range(self.start_page, max(page_numbers)+1):
                    if page_num == 1:
                        pages.append(section_url)
                    elif "/page-" in section_url:
                        pages.append(re.sub(r'/page-\d+','',section_url.rstrip('/'))+f"/page-{page_num}")
                    elif '?' in section_url:
                        pages.append(f"{section_url}&page={page_num}")
                    else:
                        pages.append(f"{section_url}?page={page_num}")
        finally:
            if soup: soup.decompose(); del soup
            if html_content: del html_content
            self.force_gc()
        return pages

    def discover_all_threads(self):
        self.log(f"🔮 Scanning section: {self.base_url}")
        all_threads = []
        pages = self.get_all_pages_urls(self.base_url)
        self.log(f"📜 Found {len(pages)} pages to scan...")

        def process_page(page_url):
            if self._stop_event.is_set(): return []
            try:
                self.log(f"  → Scanning: {page_url}")
                html_content = self.get_page(page_url)
                if not html_content: return []
                threads = self.extract_thread_links(html_content, self.base_url)
                self.log(f"  ✦ Found {len(threads)} threads on this page")
                time.sleep(self.delay)
                return threads
            except Exception as e:
                self.log(f"  ⚠ Error: {e}"); return []
            finally: self.force_gc()

        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=min(self.max_workers,6)) as executor:
            futures = [executor.submit(process_page, url) for url in pages]
            for future in as_completed(futures):
                if self._stop_event.is_set(): break
                try: all_threads.extend(future.result())
                except Exception as e: self.log(f"⚠ {e}")
                finally: self.force_gc()

        seen, unique = set(), []
        for t in all_threads:
            if t['id'] not in seen:
                seen.add(t['id']); unique.append(t)
        self.log(f"🌟 Total unique threads found: {len(unique)}")
        return unique

    def get_thread_pages(self, thread_url, html_content):
        pages = [thread_url]; soup = None
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            page_numbers = set()
            selectors = ['div.pagenav a[href]','div.pagination a[href]','div.pageNav a[href]',
                         'div.pages a[href]','td.pagenav a[href]','table.pagenav a[href]',
                         'ul.pagenav a[href]','nav.pagination a[href]',
                         'a[href*="page="]','a[href*="&page="]','a[href*="/page-"]']
            hrefs = set()
            for sel in selectors:
                for link in soup.select(sel):
                    href = link.get('href')
                    if href: hrefs.add(href)
            for href in hrefs:
                m = re.search(r'(?:[?&/](?:page|p)[=-]?)(\d+)', href)
                if m: page_numbers.add(int(m.group(1)))
            if page_numbers:
                base = re.sub(r'([?&/](?:page|p)[=-]?\d+)','',thread_url).rstrip('/')
                for i in range(2, max(page_numbers)+1):
                    if re.search(r'/page-\d+', thread_url):
                        pages.append(re.sub(r'/page-\d+','',base)+f"/page-{i}")
                    else:
                        sep = '&' if '?' in base else '?'
                        pages.append(f"{base}{sep}page={i}")
        finally:
            if soup: soup.decompose(); del soup
            self.force_gc()
        return pages

    def download_thread(self, thread):
        if self._stop_event.is_set(): return False
        thread_id    = thread['id']
        thread_url   = thread['url']
        thread_title = thread['title']
        stitle       = safe_filename(thread_title)
        self.log(f"  ⬇ Thread {thread_id}: {thread_title[:55]}...")
        html_content = thread_pages = None
        try:
            html_content = self.get_page(thread_url)
            if not html_content: return False
            thread_pages = self.get_thread_pages(thread_url, html_content)
        finally:
            if html_content: del html_content
            self.force_gc()
        downloaded_pages = 0; previous_size = None
        for page_num, page_url in enumerate(thread_pages, 1):
            if self._stop_event.is_set(): break
            filename = f"thread_{thread_id}_{stitle}__page{page_num}.html"
            filepath = os.path.join(self.output_dir, filename)
            page_content = None
            try:
                if os.path.exists(filepath):
                    downloaded_pages += 1
                    previous_size = os.path.getsize(filepath)
                    if self._media_dl and previous_size:
                        # still harvest media from already-saved files
                        with open(filepath,'r',encoding='utf-8',errors='ignore') as f:
                            saved_html = f.read()
                        self._media_dl.download_from_html(saved_html, page_url)
                    continue
                page_content = self.get_page(page_url)
                if not page_content: continue
                current_size = len(page_content.encode('utf-8'))
                if previous_size is not None and current_size == previous_size: break
                with open(filepath,'w',encoding='utf-8') as f:
                    f.write(page_content)
                downloaded_pages += 1; previous_size = current_size
                # Download media from this page if requested
                if self._media_dl:
                    self._media_dl.download_from_html(page_content, page_url)
                time.sleep(self.delay)
            except Exception as e:
                self.log(f"  ⚠ Error on page {page_num}: {e}")
            finally:
                if page_content: del page_content
                self.force_gc()
        self.metadata['threads'][thread_id] = {
            'title':thread_title,'url':thread_url,
            'pages':downloaded_pages,'downloaded_at':datetime.now().isoformat()
        }
        return True

    def run_backup(self, progress_callback=None):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        self.log("✨ Starting vBulletin section backup...")
        threads = self.discover_all_threads()
        if not threads:
            self.log("⚠ No threads found!"); return 0
        self.metadata['total_threads'] = len(threads)
        threads_to_download = [t for t in threads if t['id'] not in self.metadata['threads']]
        self.log(f"📚 Threads to download: {len(threads_to_download)}")
        successful = completed = 0

        def download_single(thread):
            try:
                result = self.download_thread(thread)
                if not result:
                    time.sleep(self.delay*2)
                    result = self.download_thread(thread)
                return result, thread
            except Exception as e:
                self.log(f"⚠ Error on thread {thread['id']}: {e}")
                return False, thread
            finally: self.force_gc()

        with ThreadPoolExecutor(max_workers=min(self.max_workers,8)) as executor:
            future_to_thread = {executor.submit(download_single,t):t for t in threads_to_download}
            for future in as_completed(future_to_thread):
                if self._stop_event.is_set(): break
                completed += 1
                try:
                    result, _ = future.result()
                    if result:
                        successful += 1
                        self.metadata['completed_threads'] = successful
                        self.save_metadata()
                    if progress_callback:
                        progress_callback(completed, len(threads_to_download))
                    self.log(f"  ✦ Progress: {completed}/{len(threads_to_download)} threads")
                except Exception as e:
                    self.log(f"⚠ {e}")
                finally: self.force_gc()

        self.log(f"🏆 Backup complete! {successful}/{len(threads)} threads downloaded.")
        self.save_metadata()
        return successful


# ─────────────────────────────────────────────
#  HTML CONVERTER  (replaces old txt converter)
# ─────────────────────────────────────────────

HTML_CSS = """
:root {
  --bg:        #0d0b14;
  --bg2:       #13101f;
  --bg3:       #1a1530;
  --gold:      #c9a84c;
  --gold2:     #e8c96a;
  --purp:      #7b4fa6;
  --teal:      #3ecfcf;
  --text:      #e8dfc8;
  --dim:       #8a7f9a;
  --border:    #2e1f55;
  --op-bg:     #1e1835;
  --re-bg:     #160f2a;
  --tag:       #3d2a6e;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { scroll-behavior: smooth; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: 'Palatino Linotype', Palatino, Georgia, serif;
  font-size: 16px;
  line-height: 1.75;
  min-height: 100vh;
}
/* ── HEADER ── */
#site-header {
  background: linear-gradient(160deg, #0d0920 0%, #1a0d35 60%, #0a0612 100%);
  border-bottom: 1px solid var(--border);
  padding: 48px 32px 36px;
  text-align: center;
  position: relative;
  overflow: hidden;
}
#site-header::before {
  content: 'ᚠ ᚢ ᚦ ᚨ ᚱ ᚲ ᚷ ᚹ ᚺ ᚾ ᛁ ᛃ ᛇ ᛈ ᛉ ᛊ ᛏ ᛒ ᛖ ᛗ ᛚ ᛜ ᛞ ᛟ';
  position: absolute; top: 8px; left: 0; right: 0;
  font-size: 14px; letter-spacing: 10px; color: #2a1a4e;
  pointer-events: none; white-space: nowrap; overflow: hidden;
}
#site-header::after {
  content: 'ᛟ ᛞ ᛜ ᛚ ᛗ ᛖ ᛒ ᛏ ᛊ ᛉ ᛈ ᛇ ᛃ ᛁ ᚾ ᚺ ᚹ ᚷ ᚲ ᚱ ᚨ ᚦ ᚢ ᚠ';
  position: absolute; bottom: 6px; left: 0; right: 0;
  font-size: 14px; letter-spacing: 10px; color: #2a1a4e;
  pointer-events: none; white-space: nowrap; overflow: hidden;
}
.header-sigil { font-size: 36px; margin-bottom: 10px; opacity: 0.6; }
h1.site-title {
  font-size: clamp(22px, 4vw, 36px);
  color: var(--gold);
  letter-spacing: 3px;
  font-weight: bold;
  text-shadow: 0 0 30px rgba(201,168,76,0.4);
}
.site-sub {
  margin-top: 8px;
  font-size: 14px;
  color: var(--dim);
  font-style: italic;
  letter-spacing: 1px;
}
/* ── LAYOUT ── */
.container { max-width: 1100px; margin: 0 auto; padding: 32px 20px 60px; }
/* ── INDEX ── */
#toc {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 28px 32px;
  margin-bottom: 48px;
}
#toc h2 {
  color: var(--gold);
  font-size: 18px;
  letter-spacing: 2px;
  margin-bottom: 18px;
  display: flex;
  align-items: center;
  gap: 10px;
}
#toc h2::before { content: '✦'; color: var(--purp); }
.toc-list { list-style: none; columns: 2; column-gap: 32px; }
@media (max-width: 700px) { .toc-list { columns: 1; } }
.toc-list li { margin-bottom: 8px; break-inside: avoid; }
.toc-list a {
  color: var(--teal);
  text-decoration: none;
  font-size: 14px;
  transition: color .2s;
  display: flex; align-items: flex-start; gap: 6px;
}
.toc-list a::before { content: 'ᛊ'; font-size: 11px; color: var(--purp); flex-shrink: 0; margin-top: 3px; }
.toc-list a:hover { color: var(--gold2); }
/* ── THREAD BLOCK ── */
.thread-block {
  margin-bottom: 56px;
  border: 1px solid var(--border);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 4px 32px rgba(0,0,0,0.5);
}
.thread-header {
  background: linear-gradient(135deg, #1e1540 0%, #2c1a55 100%);
  padding: 22px 28px;
  display: flex;
  align-items: center;
  gap: 14px;
  border-bottom: 1px solid var(--border);
}
.thread-sigil { font-size: 22px; color: var(--purp); flex-shrink: 0; }
.thread-title {
  font-size: 20px;
  color: var(--gold2);
  font-weight: bold;
  letter-spacing: 0.5px;
  word-break: break-word;
}
.thread-count {
  margin-left: auto; flex-shrink: 0;
  font-size: 12px; color: var(--dim);
  background: var(--tag);
  padding: 4px 10px; border-radius: 20px;
}
/* ── POST ── */
.post {
  padding: 24px 28px;
  border-bottom: 1px solid #1a1235;
  transition: background .2s;
}
.post:last-child { border-bottom: none; }
.post:hover { background: rgba(255,255,255,0.015); }
.post.original { background: var(--op-bg); }
.post.reply    { background: var(--re-bg); }
.post-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.post-badge {
  font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase;
  padding: 3px 10px; border-radius: 20px; font-weight: bold;
}
.badge-original { background: var(--purp); color: #f0e8ff; }
.badge-reply    { background: var(--tag);  color: var(--teal); }
.post-author {
  color: var(--gold);
  font-weight: bold;
  font-size: 15px;
}
.post-author::before { content: '⟁ '; color: var(--purp); font-size: 12px; }
.post-date {
  color: var(--dim);
  font-size: 13px;
  font-style: italic;
}
.post-date::before { content: '· '; }
.post-body {
  color: var(--text);
  font-size: 15px;
  line-height: 1.8;
  white-space: pre-wrap;
  word-break: break-word;
}
/* ── MEDIA ── */
.post-media {
  margin-top: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.post-media img {
  max-width: 480px; max-height: 360px;
  border-radius: 8px;
  border: 1px solid var(--border);
  cursor: zoom-in;
  object-fit: contain;
  background: #0a0612;
  transition: transform .2s, box-shadow .2s;
}
.post-media img:hover {
  transform: scale(1.02);
  box-shadow: 0 0 20px rgba(123,79,166,0.5);
}
.post-media video {
  max-width: 560px;
  border-radius: 8px;
  border: 1px solid var(--border);
}
.post-media audio {
  width: 100%;
  max-width: 480px;
  filter: invert(0.8) hue-rotate(220deg);
}
.media-link {
  display: inline-flex; align-items: center; gap: 6px;
  color: var(--teal); text-decoration: none;
  font-size: 13px;
  background: var(--tag); padding: 6px 14px; border-radius: 20px;
  transition: background .2s;
}
.media-link:hover { background: var(--purp); }
/* ── LIGHTBOX ── */
#lightbox {
  display: none; position: fixed; inset: 0;
  background: rgba(0,0,0,0.92);
  z-index: 9999;
  justify-content: center; align-items: center;
  cursor: zoom-out;
}
#lightbox.open { display: flex; }
#lightbox img {
  max-width: 92vw; max-height: 92vh;
  border-radius: 10px;
  box-shadow: 0 0 60px rgba(123,79,166,0.6);
}
/* ── SCROLL TOP ── */
#scroll-top {
  position: fixed; bottom: 28px; right: 28px;
  background: var(--purp); color: var(--gold);
  border: none; border-radius: 50%;
  width: 46px; height: 46px; font-size: 20px;
  cursor: pointer;
  box-shadow: 0 0 16px rgba(123,79,166,0.5);
  display: none; align-items: center; justify-content: center;
  transition: background .2s;
  z-index: 100;
}
#scroll-top:hover { background: var(--gold); color: var(--bg); }
/* ── FOOTER ── */
footer {
  text-align: center; padding: 28px;
  font-size: 13px; color: var(--dim);
  border-top: 1px solid var(--border);
  letter-spacing: 1px;
}
footer span { color: var(--purp); }
"""

HTML_JS = """
// Lightbox
const lb = document.getElementById('lightbox');
const lbImg = lb.querySelector('img');
document.querySelectorAll('.post-media img').forEach(img => {
  img.addEventListener('click', () => {
    lbImg.src = img.src;
    lb.classList.add('open');
  });
});
lb.addEventListener('click', () => lb.classList.remove('open'));

// Scroll-to-top
const btn = document.getElementById('scroll-top');
window.addEventListener('scroll', () => {
  btn.style.display = window.scrollY > 400 ? 'flex' : 'none';
});
btn.addEventListener('click', () => window.scrollTo({top:0, behavior:'smooth'}));
"""

def _render_media_tag(url, local_path, embed_base64, media_dl):
    """Return an HTML snippet for a media file."""
    ext = get_ext(url)

    if embed_base64 and media_dl:
        src = media_dl.get_base64_uri(url)
    else:
        src = None

    # fall back to relative local path if not embedding
    if not src:
        if local_path and os.path.exists(local_path):
            src = 'media/' + os.path.basename(local_path)
        else:
            src = url  # external link as last resort

    if ext in IMAGE_EXTS:
        return f'<img src="{src}" alt="image" loading="lazy">'
    elif ext in VIDEO_EXTS:
        return f'<video src="{src}" controls preload="metadata"></video>'
    elif ext in AUDIO_EXTS:
        return f'<audio src="{src}" controls></audio>'
    else:
        fname = os.path.basename(urlparse(url).path) or 'file'
        return f'<a class="media-link" href="{src}" download="{fname}">⬇ {fname}</a>'


def extract_posts_html(file_path, media_dl=None, embed_base64=False):
    """Parse one saved HTML page and return (thread_title, list_of_post_dicts)."""
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        raw = f.read()

    soup = BeautifulSoup(raw, 'html.parser')
    for tag in soup(['script','style','meta','noscript','link']):
        tag.decompose()

    title_tag    = soup.find('title')
    thread_title = clean_text(title_tag.text) if title_tag else "Untitled"

    # Try to recover base URL from metadata or og:url
    base_url = ""
    og = soup.find('meta', property='og:url')
    if og and og.get('content'):
        base_url = og['content']

    message_blocks = soup.find_all('div', class_='message-userContent')
    posts = []
    for block in message_blocks:
        desc     = block.get('data-lb-caption-desc', '')
        author   = "Unknown user"
        date     = "Unknown date"
        date_obj = None
        if '·' in desc:
            parts = desc.split('·')
            if len(parts) >= 2:
                author   = clean_text(parts[0])
                date     = clean_text(parts[1])
                date_obj = parse_date(date)

        message_div = block.find_next('div', class_='bbWrapper')
        body_text   = ""
        media_tags  = []

        if message_div:
            # collect media inside the post
            for img in message_div.find_all('img', src=True):
                full_url = urljoin(base_url, img['src']) if base_url else img['src']
                local    = media_dl.get_local_path(full_url) if media_dl else None
                if local or (media_dl and get_ext(full_url) in MEDIA_EXTS):
                    media_tags.append(_render_media_tag(full_url, local, embed_base64, media_dl))

            for tag in message_div.find_all(['video','audio'], src=True):
                full_url = urljoin(base_url, tag['src']) if base_url else tag['src']
                local    = media_dl.get_local_path(full_url) if media_dl else None
                media_tags.append(_render_media_tag(full_url, local, embed_base64, media_dl))

            body_text = clean_text(message_div.get_text())

        posts.append({
            'date_obj': date_obj,
            'author':   author,
            'date':     date,
            'body':     body_text,
            'media':    media_tags,
        })

    posts.sort(key=lambda x: (x['date_obj'] is None, x['date_obj']))
    soup.decompose()
    return thread_title, posts


def build_html_output(all_threads, generated_at, forum_url=""):
    """Build the final complete HTML string from list of (title, posts) tuples."""
    # index
    toc_items = ""
    for idx, (title, _posts) in enumerate(all_threads):
        anchor = f"thread-{idx}"
        toc_items += f'<li><a href="#{anchor}">{title}</a></li>\n'

    # threads
    thread_blocks = ""
    for idx, (title, posts) in enumerate(all_threads):
        anchor    = f"thread-{idx}"
        post_html = ""
        for pi, post in enumerate(posts):
            is_op   = pi == 0
            cls     = "post original" if is_op else "post reply"
            badge   = '<span class="post-badge badge-original">Original Post</span>' if is_op \
                      else '<span class="post-badge badge-reply">Reply</span>'
            media_html = ""
            if post['media']:
                media_html = '<div class="post-media">' + '\n'.join(post['media']) + '</div>'

            # escape HTML in body but preserve newlines
            safe_body = post['body'].replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

            post_html += f"""
<div class="{cls}">
  <div class="post-meta">
    {badge}
    <span class="post-author">{post['author']}</span>
    <span class="post-date">{post['date']}</span>
  </div>
  <div class="post-body">{safe_body}</div>
  {media_html}
</div>"""

        thread_blocks += f"""
<div class="thread-block" id="{anchor}">
  <div class="thread-header">
    <span class="thread-sigil">ᛟ</span>
    <div class="thread-title">{title}</div>
    <span class="thread-count">{len(posts)} post{'s' if len(posts)!=1 else ''}</span>
  </div>
  {post_html}
</div>"""

    forum_line = f'<br><span style="color:var(--teal);font-size:12px">{forum_url}</span>' if forum_url else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="shortcut icon" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAB2ElEQVR42t2RzU7bQBSFr0twyK+VJjRulTRR+wR9ARasuq+6gLLrorQB9hXqsqjP0j3KE7RKUie2oQiCG/8kKmDHdVEAO4TxXMYRGyTEA3A0o9HM6NO951x4gPoDkvA/Ln8KhG59ku8dTAq9g2C+W/cy6keNa2TvhV2+vUJyuoPzJmLRQhTZfmYhLfURnw8wLBv2MCUv3wmPEjvfMG8Skjcc+sT0/yXlmg6NogEt0c2q67Ri+qRiOPiiT07Tu19vwd6c8oU+NsduQlph8JmblmtuulOjJTO4LGo/EL7PuIKyHlbNkTMnv8OcMfZi6uYUtmPtRVY5tPnOm6PZ1gI+tagBv0RatnysDNAXu3UJ2rPHIBWYJXoUay0MZ6S3CHpoQ2PxEQIAcjetRBeOLS7goiN6T6SSr19VCzaBMQ+XAEAAMKRcAGO4gvDGQlLdRNEMnIS8REvWmZtV1qLUadXyacXyvaTywY2rGySuj1yu8/6c2/NPoPn5Vg6nmd0tLPcJS9qJAmOe1yIr0xB5dQN5wyegDc/hNz2G1hbcpWGqsxyWdBtfDpBW+9MxUsFEBiNCD0ewc/IXfi7BfdKgmfUEZTXIdbcnmcP9SUzbv4C9bRuaq4fsDx6ergG59xON7jX+PgAAAABJRU5ErkJggg==" />
<title>✦ Arcane Forum Archive ✦</title>
<style>{HTML_CSS}</style>
</head>
<body>

<header id="site-header">
  <div class="header-sigil">ᚠ ᛟ ᚱ ᚢ ᛗ</div>
  <h1 class="site-title">✦ ARCANE FORUM ARCHIVE ✦</h1>
  <div class="site-sub">Mystical preservation of digital knowledge &nbsp;·&nbsp; {generated_at}{forum_line}</div>
</header>

<div class="container">

  <nav id="toc">
    <h2>Thread Index — {len(all_threads)} scrolls</h2>
    <ul class="toc-list">
{toc_items}
    </ul>
  </nav>

{thread_blocks}

</div>

<div id="lightbox"><img src="" alt=""></div>
<button id="scroll-top" title="Back to top">↑</button>

<footer>
  ✦ &nbsp; Generated by <span>Arcane Forum Archiver</span> &nbsp;·&nbsp; {generated_at} &nbsp; ✦
</footer>

<script>{HTML_JS}</script>
</body>
</html>"""


def convert_html_folder(input_dir, output_file, log_callback=None, progress_callback=None,
                        stop_event=None, media_dl=None, embed_base64=False, forum_url=""):
    log = log_callback or print
    html_files = [os.path.join(input_dir, f)
                  for f in os.listdir(input_dir) if f.lower().endswith('.html')
                  and not f.startswith('_')]  # skip index files
    if not html_files:
        log("⚠ No HTML files found in the folder.")
        return 0
    log(f"📜 Found {len(html_files)} HTML files to convert...")

    all_threads = []
    for i, filepath in enumerate(sorted(html_files), 1):
        if stop_event and stop_event.is_set():
            break
        try:
            title, posts = extract_posts_html(filepath, media_dl=media_dl, embed_base64=embed_base64)
            if posts:
                all_threads.append((title, posts))
        except Exception as e:
            log(f"  ⚠ Error in {os.path.basename(filepath)}: {e}")
        if progress_callback:
            progress_callback(i, len(html_files))
        log(f"  ✦ Parsed {i}/{len(html_files)}: {os.path.basename(filepath)}")

    log("🎨 Weaving the HTML grimoire...")
    generated_at = datetime.now().strftime("%B %d, %Y at %H:%M")
    html_out = build_html_output(all_threads, generated_at, forum_url)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_out)

    size_mb = os.path.getsize(output_file) / 1024 / 1024
    log(f"✅ HTML grimoire sealed! {output_file}  ({size_mb:.1f} MB,  {len(all_threads)} threads)")
    return len(all_threads)


# ─────────────────────────────────────────────
#  RESTORATION ENGINE
# ─────────────────────────────────────────────

import csv
import os
import random
import string

# ── BBCode converter ─────────────────────────────────────

def _html_to_bbcode(element):
    """
    Recursively walk a BeautifulSoup Tag and produce BBCode text.
    Handles: b/strong, i/em, u, s/strike, a, img, blockquote, code,
             h1-h6, ul/ol/li, br, p — everything else falls back to plain text.
    """
    from bs4 import NavigableString, Tag

    if isinstance(element, NavigableString):
        return str(element)

    if not isinstance(element, Tag):
        return ""

    tag  = element.name.lower() if element.name else ""
    inner = "".join(_html_to_bbcode(c) for c in element.children)

    if tag in ("b", "strong"):
        return f"[B]{inner}[/B]"
    if tag in ("i", "em"):
        return f"[I]{inner}[/I]"
    if tag == "u":
        return f"[U]{inner}[/U]"
    if tag in ("s", "strike", "del"):
        return f"[S]{inner}[/S]"
    if tag == "a":
        href = element.get("href", "")
        return f"[URL={href}]{inner}[/URL]" if href else inner
    if tag == "img":
        src = element.get("src", "")
        if src.startswith("data:"):
            return "[IMG]<embedded>[/IMG]"
        return f"[IMG]{src}[/IMG]"
    if tag == "blockquote":
        return f"[QUOTE]{inner}[/QUOTE]"
    if tag in ("code", "pre"):
        return f"[CODE]{inner}[/CODE]"
    if tag in ("h1","h2","h3","h4","h5","h6"):
        size = {"h1":"6","h2":"5","h3":"4","h4":"3","h5":"2","h6":"1"}.get(tag,"4")
        return f"[SIZE={size}][B]{inner}[/B][/SIZE]\n"
    if tag == "br":
        return "\n"
    if tag == "p":
        return inner.strip() + "\n\n"
    if tag in ("ul", "ol"):
        return f"[LIST]\n{inner}[/LIST]\n"
    if tag == "li":
        return f"[*]{inner.strip()}\n"
    if tag in ("div", "span", "section", "article"):
        return inner
    # drop head/script/style completely
    if tag in ("script","style","head","meta","link","noscript"):
        return ""
    return inner


def _clean_bbcode(text):
    """Collapse excessive blank lines and strip leading/trailing whitespace."""
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ── Random hex filename ───────────────────────────────────

def _random_media_name(ext):
    """Generate a random hex-like filename: e.g. a3f9c2d0814b.png"""
    hex_part = ''.join(random.choices(string.hexdigits[:16], k=14))
    digit_part = ''.join(random.choices(string.digits, k=8))
    name = hex_part + digit_part
    return name + ext


# ── Base64 media extractor ────────────────────────────────

def _extract_b64_media(src_attr, recovered_dir, log):
    """
    If src_attr is a data: URI, decode and save to recovered_dir.
    Returns (saved_filepath, mime) or (None, None).
    """
    if not src_attr.startswith("data:"):
        return None, None
    try:
        # data:<mime>;base64,<data>
        header, b64data = src_attr.split(",", 1)
        mime = header.split(":")[1].split(";")[0].strip()
        ext  = mimetypes.guess_extension(mime) or ".bin"
        # normalise common extensions
        ext  = {".jpe": ".jpg", ".jpeg": ".jpg"}.get(ext, ext)
        fname = _random_media_name(ext)
        fpath = os.path.join(recovered_dir, fname)
        raw   = base64.b64decode(b64data + "==")   # pad safely
        with open(fpath, "wb") as f:
            f.write(raw)
        log(f"    ✦ Materialised {mime} → {fname}")
        return fpath, mime
    except Exception as e:
        log(f"    ⚠ Base64 decode failed: {e}")
        return None, None


# ── Core: parse a single HTML archive file ───────────────

def _parse_single_html(html_filepath, log, se):
    """
    Parse ONE HTML file (the Arcane archive or any vBulletin HTML).
    Returns (all_threads, csv_rows, total_posts, recovered_dir).

    Supports two HTML structures:
      1. Arcane Archive format  — .thread-block + .post elements (our own output)
      2. Raw vBulletin format   — div.message-userContent + div.bbWrapper
    """
    html_dir      = os.path.dirname(os.path.abspath(html_filepath))
    recovered_dir = os.path.join(html_dir, "recovered_media")
    os.makedirs(recovered_dir, exist_ok=True)

    log(f"ᚱ  Opening scroll: {os.path.basename(html_filepath)}")
    try:
        with open(html_filepath, "r", encoding="utf-8", errors="ignore") as f:
            raw_html = f.read()
    except Exception as e:
        log(f"⚠  Cannot open file: {e}")
        return [], [], 0, recovered_dir

    all_threads = []
    csv_rows    = []
    total_posts = 0

    try:
        soup = BeautifulSoup(raw_html, "html.parser")

        # ── Detect format ──────────────────────────────────
        # Arcane Archive: contains .thread-block divs with .thread-title and .post divs
        arcane_threads = soup.find_all("div", class_="thread-block")
        is_arcane = len(arcane_threads) > 0

        if is_arcane:
            log(f"ᛊ  Arcane Archive format detected — {len(arcane_threads)} thread block(s)")

            for t_idx, t_block in enumerate(arcane_threads):
                if se.is_set(): break

                # Title
                title_el     = t_block.find(class_="thread-title")
                thread_title = clean_text(title_el.get_text()) if title_el else f"Thread {t_idx+1}"

                post_divs  = t_block.find_all("div", class_="post")
                posts_data = []

                for p_idx, post_div in enumerate(post_divs):
                    if se.is_set(): break

                    author_el = post_div.find(class_="post-author")
                    date_el   = post_div.find(class_="post-date")
                    body_el   = post_div.find(class_="post-body")

                    author   = clean_text(author_el.get_text()) if author_el else "Unknown Scribe"
                    # strip the '⟁ ' prefix if present
                    author   = author.lstrip("⟁ ").strip()
                    date_str = clean_text(date_el.get_text()) if date_el else "Date unknown"
                    date_str = date_str.lstrip("· ").strip()

                    bbcode_body = ""
                    media_refs  = []

                    if body_el:
                        # media recovery from post-media sibling
                        media_container = post_div.find(class_="post-media")
                        if media_container:
                            for img_tag in media_container.find_all("img"):
                                src = img_tag.get("src","")
                                if src.startswith("data:"):
                                    fpath, mime = _extract_b64_media(src, recovered_dir, log)
                                    if fpath:
                                        rel = os.path.join("recovered_media", os.path.basename(fpath))
                                        media_refs.append({"type":"image","source":"base64","mime":mime,"local_path":rel})
                                elif src:
                                    media_refs.append({"type":"image","source":"url","url":src})
                            for vid in media_container.find_all(["video","source"]):
                                src = vid.get("src","")
                                if src.startswith("data:"):
                                    fpath, mime = _extract_b64_media(src, recovered_dir, log)
                                    if fpath:
                                        rel = os.path.join("recovered_media", os.path.basename(fpath))
                                        media_refs.append({"type":"video","source":"base64","mime":mime,"local_path":rel})
                                elif src:
                                    media_refs.append({"type":"video","source":"url","url":src})

                        # body text is pre-escaped plain text in post-body
                        raw_body = body_el.get_text()
                        bbcode_body = _clean_bbcode(raw_body)

                    is_op = "original" in (post_div.get("class") or [])
                    posts_data.append({
                        "index": p_idx, "author": author, "date": date_str,
                        "bbcode": bbcode_body, "media": media_refs, "is_original": is_op,
                    })
                    media_str = " | ".join(r.get("local_path") or r.get("url","") for r in media_refs)
                    csv_rows.append({
                        "thread_title": thread_title, "post_author": author,
                        "post_date": date_str, "post_content_bbcode": bbcode_body[:2000],
                        "media_references": media_str,
                    })

                if posts_data:
                    log(f"  ✦ Thread '{thread_title[:55]}' — {len(posts_data)} posts")
                all_threads.append({
                    "thread_title": thread_title,
                    "source_file":  os.path.basename(html_filepath),
                    "post_count":   len(posts_data),
                    "posts":        posts_data,
                })
                total_posts += len(posts_data)

        else:
            # ── Raw vBulletin format ──────────────────────
            log("ᛊ  Raw vBulletin format detected")
            title_tag    = soup.find("title")
            thread_title = clean_text(title_tag.get_text()) if title_tag else "Untitled Scroll"
            message_blocks = soup.find_all("div", class_="message-userContent")
            log(f"ᛟ  Found {len(message_blocks)} post block(s)")

            posts_data = []
            for block_idx, block in enumerate(message_blocks):
                if se.is_set(): break

                desc = block.get("data-lb-caption-desc","")
                author = "Unknown Scribe"; date_str = "Date unknown"
                if "·" in desc:
                    parts = desc.split("·")
                    if len(parts) >= 2:
                        author   = clean_text(parts[0])
                        date_str = clean_text(parts[1])

                message_div = block.find_next("div", class_="bbWrapper")
                bbcode_body = ""; media_refs = []

                if message_div:
                    for img_tag in message_div.find_all("img"):
                        src = img_tag.get("src","")
                        if src.startswith("data:"):
                            fpath, mime = _extract_b64_media(src, recovered_dir, log)
                            if fpath:
                                rel = os.path.join("recovered_media", os.path.basename(fpath))
                                media_refs.append({"type":"image","source":"base64","mime":mime,"local_path":rel})
                                img_tag["src"] = rel
                        elif src:
                            media_refs.append({"type":"image","source":"url","url":src})
                    for vid_tag in message_div.find_all(["video","source"]):
                        src = vid_tag.get("src","")
                        if src.startswith("data:"):
                            fpath, mime = _extract_b64_media(src, recovered_dir, log)
                            if fpath:
                                rel = os.path.join("recovered_media", os.path.basename(fpath))
                                media_refs.append({"type":"video","source":"base64","mime":mime,"local_path":rel})
                                vid_tag["src"] = rel
                        elif src:
                            media_refs.append({"type":"video","source":"url","url":src})
                    for a_tag in message_div.find_all("a", href=True):
                        href = a_tag["href"]
                        if get_ext(href) in MEDIA_EXTS and not href.startswith("data:"):
                            media_refs.append({"type":"file","source":"url","url":href})
                    try:
                        bbcode_body = _clean_bbcode(_html_to_bbcode(message_div))
                    except Exception as e:
                        log(f"    ⚠ BBCode error: {e}")
                        bbcode_body = clean_text(message_div.get_text())

                posts_data.append({
                    "index": block_idx, "author": author, "date": date_str,
                    "bbcode": bbcode_body, "media": media_refs, "is_original": block_idx == 0,
                })
                media_str = " | ".join(r.get("local_path") or r.get("url","") for r in media_refs)
                csv_rows.append({
                    "thread_title": thread_title, "post_author": author,
                    "post_date": date_str, "post_content_bbcode": bbcode_body[:2000],
                    "media_references": media_str,
                })

            all_threads.append({
                "thread_title": thread_title,
                "source_file":  os.path.basename(html_filepath),
                "post_count":   len(posts_data),
                "posts":        posts_data,
            })
            total_posts += len(posts_data)
            log(f"  ✦ Extracted {total_posts} posts from '{thread_title[:55]}'")

        soup.decompose()

    except Exception as e:
        log(f"⚠  Parse error: {e}")

    return all_threads, csv_rows, total_posts, recovered_dir


# ── Write helpers (called individually by each button) ───

def restoration_write_json(all_threads, total_posts, out_path, log):
    """Serialize parsed data to JSON. Returns path or None."""
    log("ᛊ  Inscribing the JSON codex...")
    try:
        payload = {
            "generated_at":  datetime.now().isoformat(),
            "total_threads": len(all_threads),
            "total_posts":   total_posts,
            "threads":       all_threads,
        }
        with open(out_path, "w", encoding="utf-8") as jf:
            json.dump(payload, jf, indent=2, ensure_ascii=False)
        size_kb = os.path.getsize(out_path) / 1024
        log(f"  ✅ JSON codex sealed: {os.path.basename(out_path)}  ({size_kb:.1f} KB)")
        return out_path
    except Exception as e:
        log(f"  ⚠ JSON write failed: {e}")
        return None


def restoration_write_csv(csv_rows, out_path, log):
    """Serialize parsed data to CSV. Returns path or None."""
    log("ᚠ  Etching the CSV tablet...")
    try:
        fieldnames = ["thread_title","post_author","post_date","post_content_bbcode","media_references"]
        with open(out_path, "w", encoding="utf-8", newline="") as cf:
            writer = csv.DictWriter(cf, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
            writer.writeheader()
            writer.writerows(csv_rows)
        size_kb = os.path.getsize(out_path) / 1024
        log(f"  ✅ CSV tablet chiselled: {os.path.basename(out_path)}  ({size_kb:.1f} KB)")
        return out_path
    except Exception as e:
        log(f"  ⚠ CSV write failed: {e}")
        return None


# ─────────────────────────────────────────────
#  WEBSITE MIRROR ENGINE  (ᚹ)
# ─────────────────────────────────────────────

class MirrorCrawler:
    """
    Full-site mirror crawler adapted from the standalone script.
    Downloads every page + asset of a website, rewriting internal links
    to relative local paths so the mirror works offline.
    """

    def __init__(self, base_url, output_dir="mirror",
                 max_workers=8, delay=0.5,
                 log_callback=None, stop_event=None,
                 progress_callback=None):
        self.base_url          = base_url.rstrip("/")
        self.base_domain       = urlparse(base_url).netloc
        self.output_dir        = output_dir
        self.max_workers       = max_workers
        self.delay             = delay
        self.log               = log_callback or print
        self._stop             = stop_event or threading.Event()
        self._progress_cb      = progress_callback

        self.visited           = set()
        self.visited_lock      = threading.Lock()
        self.queue             = Queue()

        self._downloaded       = 0
        self._count_lock       = threading.Lock()

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

    # ── URL helpers ───────────────────────────────────────

    def _normalize(self, url):
        url, _ = urldefrag(url)
        return url.rstrip("/")

    def _url_to_path(self, url):
        parsed = urlparse(url)
        path   = parsed.path or "/"
        if path == "" or path.endswith("/"):
            path += "index.html"
        elif "." not in os.path.basename(path):
            # no extension → treat as directory index
            path = path.rstrip("/") + "/index.html"
        elif path.lower().endswith(".php"):
            path = path + ".html"
        return os.path.join(self.output_dir, parsed.netloc.replace(":", "_") + path)

    def _save(self, path, content):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(content)
        except Exception as e:
            self.log(f"  ⚠ Save error ({os.path.basename(path)}): {e}")

    # ── Worker ────────────────────────────────────────────

    def _worker(self):
        while not self._stop.is_set():
            try:
                url = self.queue.get(timeout=2)
            except Exception:
                # queue empty — keep waiting until join() unblocks
                if self._stop.is_set():
                    break
                continue

            if url is None:
                self.queue.task_done()
                break

            url = self._normalize(url)

            with self.visited_lock:
                if url in self.visited:
                    self.queue.task_done()
                    continue
                self.visited.add(url)

            try:
                resp = self.session.get(url, timeout=12, stream=False)
                time.sleep(self.delay)
            except Exception as e:
                self.log(f"  ⚠ Fetch error: {url}  ({e})")
                self.queue.task_done()
                continue

            if resp.status_code != 200:
                self.log(f"  ⚠ HTTP {resp.status_code}: {url}")
                self.queue.task_done()
                continue

            ctype     = resp.headers.get("Content-Type", "")
            local_out = self._url_to_path(url)

            if "text/html" in ctype:
                try:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for tag in soup.find_all(["a", "link", "script", "img",
                                              "video", "audio", "source"]):
                        attr = "href" if tag.name in ("a", "link") else "src"
                        link = tag.get(attr)
                        if not link or link.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
                            continue
                        absolute = self._normalize(urljoin(url, link))
                        if urlparse(absolute).netloc != self.base_domain:
                            continue
                        child_path = self._url_to_path(absolute)
                        try:
                            rel = os.path.relpath(child_path,
                                                  os.path.dirname(self._url_to_path(url)))
                            tag[attr] = rel.replace("\\", "/")
                        except ValueError:
                            pass  # different drives on Windows — skip rewrite
                        self.queue.put(absolute)

                    self._save(local_out, soup.encode())
                except Exception as e:
                    self.log(f"  ⚠ HTML parse error: {e}")
                    self._save(local_out, resp.content)
            else:
                self._save(local_out, resp.content)

            with self._count_lock:
                self._downloaded += 1
                n = self._downloaded

            self.log(f"  ✦ [{n}] {url}")
            if self._progress_cb:
                self._progress_cb(n)

            self.queue.task_done()

    # ── Entry point ───────────────────────────────────────

    def run(self):
        self.log(f"🌐 Starting mirror of: {self.base_url}")
        self.log(f"📁 Output folder: {self.output_dir}")
        os.makedirs(self.output_dir, exist_ok=True)

        self.queue.put(self.base_url)

        threads = []
        for _ in range(self.max_workers):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            threads.append(t)

        # Wait until queue is empty or stop requested
        while not self._stop.is_set():
            if self.queue.empty() and self.queue.unfinished_tasks == 0:
                break
            time.sleep(0.4)

        # Graceful shutdown
        if self._stop.is_set():
            self.log("⏹  Stop requested — draining queue...")
            with self.queue.mutex:
                self.queue.queue.clear()
                self.queue.all_tasks_done.notify_all()
                self.queue.unfinished_tasks = 0

        for _ in threads:
            self.queue.put(None)
        for t in threads:
            t.join(timeout=6)

        n = self._downloaded
        self.log(f"🏆 Mirror complete — {n} file(s) saved to: {self.output_dir}")
        return n


# ─────────────────────────────────────────────
#  RUNE ANIMATOR
# ─────────────────────────────────────────────

class RuneAnimator:
    def __init__(self, canvas, width, height):
        import random
        self.canvas   = canvas
        self.width    = width
        self.height   = height
        self.runes    = []
        self._running = True
        for _ in range(28):
            x      = random.randint(0, width)
            y      = random.randint(0, height)
            symbol = random.choice(RUNE_SYMBOLS)
            color  = random.choice([BORDER_GLOW, ACCENT_PURP, "#251840", "#1e1535"])
            size   = random.randint(13, 28)
            speed  = random.uniform(0.25, 0.9)
            item   = canvas.create_text(x, y, text=symbol, fill=color, font=("Segoe UI", size))
            self.runes.append({'item': item, 'dy': random.choice([-1,1]) * speed})
        self._animate()

    def resize(self, new_width, new_height):
        """Called whenever the header canvas is resized."""
        import random
        self.width  = new_width
        self.height = new_height
        # Spread runes that are now outside the new width across the full new width
        for rune in self.runes:
            coords = self.canvas.coords(rune['item'])
            if coords and (coords[0] < 0 or coords[0] > new_width):
                self.canvas.coords(rune['item'],
                    random.randint(0, new_width), coords[1])

    def _animate(self):
        if not self._running: return
        for rune in self.runes:
            self.canvas.move(rune['item'], 0, rune['dy'])
            coords = self.canvas.coords(rune['item'])
            if coords:
                y = coords[1]
                if y < -30 or y > self.height + 30:
                    rune['dy'] = -rune['dy']
        self.canvas.after(55, self._animate)

    def stop(self):
        self._running = False


# ─────────────────────────────────────────────
#  MAIN GUI
# ─────────────────────────────────────────────

class ArcaneForumArchiver(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("✦ Arcane Forum Archiver ✦")
        self.geometry("1100x940")
        self.minsize(950, 800)
        self.configure(bg=BG_DEEP)
        self.resizable(True, True)

        self._stop_event       = threading.Event()
        self._backup_obj       = None
        self._mi_stop          = threading.Event()  # mirror has its own stop
        self._rune_initialized = False
        self._title_ids        = []

        self._setup_fonts()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Fonts ────────────────────────────────────────────

    def _setup_fonts(self):
        try:
            fam = "Palatino Linotype"
            self.font_title  = tkfont.Font(family=fam, size=26, weight="bold")
            self.font_sub    = tkfont.Font(family=fam, size=14, slant="italic")
            self.font_label  = tkfont.Font(family=fam, size=14)
            self.font_btn    = tkfont.Font(family=fam, size=14, weight="bold")
            self.font_log    = tkfont.Font(family="Courier New", size=12)
            self.font_tab    = tkfont.Font(family=fam, size=14, weight="bold")
            self.font_spin   = tkfont.Font(family="Courier New", size=13)
            self.font_status = tkfont.Font(family=fam, size=13)
            self.font_phase  = tkfont.Font(family=fam, size=13, slant="italic")
            self.font_chk    = tkfont.Font(family=fam, size=13)
        except:
            self.font_title  = tkfont.Font(size=24, weight="bold")
            self.font_sub    = tkfont.Font(size=13, slant="italic")
            self.font_label  = tkfont.Font(size=13)
            self.font_btn    = tkfont.Font(size=13, weight="bold")
            self.font_log    = tkfont.Font(family="Courier", size=12)
            self.font_tab    = tkfont.Font(size=14, weight="bold")
            self.font_spin   = tkfont.Font(family="Courier", size=12)
            self.font_status = tkfont.Font(size=12)
            self.font_phase  = tkfont.Font(size=12, slant="italic")
            self.font_chk    = tkfont.Font(size=12)

    # ── Top-level build ──────────────────────────────────

    def _build_ui(self):
        # header
        self.header_canvas = tk.Canvas(self, height=140, bg=BG_DEEP, highlightthickness=0)
        self.header_canvas.pack(fill="x")
        self.header_canvas.bind("<Configure>", self._on_header_resize)

        # notebook
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Arcane.TNotebook",
            background=BG_DEEP, borderwidth=0, tabmargins=[6,6,0,0])
        style.configure("Arcane.TNotebook.Tab",
            background=BG_PANEL, foreground=TEXT_DIM,
            font=self.font_tab, padding=[26,12], borderwidth=0)
        style.map("Arcane.TNotebook.Tab",
            background=[("selected", ACCENT_PURP)],
            foreground=[("selected", ACCENT_GOLD)])

        self.notebook = ttk.Notebook(self, style="Arcane.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=14, pady=10)

        self.tab_backup  = tk.Frame(self.notebook, bg=BG_MID)
        self.tab_convert = tk.Frame(self.notebook, bg=BG_MID)
        self.tab_fullop  = tk.Frame(self.notebook, bg=BG_MID)
        self.tab_restore = tk.Frame(self.notebook, bg=BG_DEEP)
        self.tab_mirror  = tk.Frame(self.notebook, bg=BG_MID)

        self.notebook.add(self.tab_backup,  text="  ᚠ  Forum Backup  ")
        self.notebook.add(self.tab_convert, text="  ᛊ  Convert → HTML  ")
        self.notebook.add(self.tab_fullop,  text="  ᛟ  Backup + Convert  ")
        self.notebook.add(self.tab_restore, text="  ᚨ  Restoration Ritual  ")
        self.notebook.add(self.tab_mirror,  text="  ᚹ  Website Mirror  ")

        self._build_tab_backup()
        self._build_tab_convert()
        self._build_tab_fullop()
        self._build_tab_restore()
        self._build_tab_mirror()

        # status bar
        self.status_var = tk.StringVar(value="✦   Ready for the ritual   ✦")
        tk.Label(self, textvariable=self.status_var,
            bg=BG_PANEL, fg=ACCENT_TEAL, font=self.font_status,
            anchor="w", padx=18, pady=8, bd=0, relief="flat"
        ).pack(fill="x", side="bottom")

    def _on_header_resize(self, event):
        w = event.width; cx = w // 2
        for tid in self._title_ids:
            self.header_canvas.delete(tid)
        self._title_ids = []
        self._title_ids.append(self.header_canvas.create_text(
            cx, 48, text="✦   ARCANE FORUM ARCHIVER   ✦",
            fill=ACCENT_GOLD, font=self.font_title, anchor="center"))
        self._title_ids.append(self.header_canvas.create_text(
            cx, 92, text="vBulletin Backup & Conversion  —  The Mystical Art of Data Preservation",
            fill=TEXT_DIM, font=self.font_sub, anchor="center"))
        self._title_ids.append(self.header_canvas.create_line(
            30, 120, w-30, 120, fill=BORDER_GLOW, width=1))
        if not self._rune_initialized and w > 100:
            self._rune_initialized = True
            self.rune_animator = RuneAnimator(self.header_canvas, w, 140)
        elif self._rune_initialized:
            self.rune_animator.resize(w, 140)

    # ── Widget helpers ───────────────────────────────────

    def _section(self, parent, title):
        lf = tk.LabelFrame(parent, text=f"   {title}   ",
            bg=BG_MID, fg=ACCENT_GOLD, font=self.font_sub,
            bd=1, relief="groove",
            highlightbackground=BORDER_GLOW, highlightthickness=1, labelanchor="nw")
        lf.pack(fill="x", padx=20, pady=10)
        return lf

    def _label(self, parent, text):
        return tk.Label(parent, text=text, bg=BG_MID, fg=TEXT_MAIN, font=self.font_label)

    def _entry(self, parent, textvariable=None, width=46):
        return tk.Entry(parent, textvariable=textvariable, width=width,
            bg=BG_PANEL, fg=ACCENT_TEAL, insertbackground=ACCENT_GOLD,
            relief="flat", bd=8, font=self.font_log)

    def _btn(self, parent, text, command, color=ACCENT_PURP):
        return tk.Button(parent, text=text, command=command,
            bg=color, fg=TEXT_MAIN,
            activebackground=ACCENT_GOLD, activeforeground=BG_DEEP,
            font=self.font_btn, relief="flat", bd=0,
            padx=22, pady=12, cursor="hand2")

    def _spinbox(self, parent, from_, to, textvariable, width=7, increment=1.0):
        return tk.Spinbox(parent, from_=from_, to=to, increment=increment,
            textvariable=textvariable, width=width,
            bg=BG_PANEL, fg=ACCENT_TEAL, buttonbackground=BORDER_GLOW,
            font=self.font_spin)

    def _checkbox(self, parent, text, variable, accent=ACCENT_TEAL):
        """Styled checkbox using a Canvas so we can colour it properly."""
        frame = tk.Frame(parent, bg=BG_MID)
        cb = tk.Checkbutton(frame, text=text, variable=variable,
            bg=BG_MID, fg=TEXT_MAIN,
            activebackground=BG_MID, activeforeground=ACCENT_GOLD,
            selectcolor=BG_PANEL,
            font=self.font_chk,
            bd=0, relief="flat",
            cursor="hand2")
        cb.pack(side="left")
        return frame

    def _logbox(self, parent, height=9):
        frame = tk.Frame(parent, bg=BG_PANEL, bd=1, relief="groove")
        frame.pack(fill="both", expand=True, padx=20, pady=8)
        sb = tk.Scrollbar(frame, bg=BORDER_GLOW, troughcolor=BG_DEEP, activebackground=ACCENT_PURP)
        sb.pack(side="right", fill="y")
        box = tk.Text(frame, height=height, font=self.font_log,
            bg=BG_PANEL, fg=TEXT_MAIN, insertbackground=ACCENT_GOLD,
            yscrollcommand=sb.set, state="disabled", bd=0, wrap="word")
        box.pack(fill="both", expand=True, padx=6, pady=6)
        sb.config(command=box.yview)
        return box

    def _progressbar(self, parent):
        style = ttk.Style()
        style.configure("Arcane.Horizontal.TProgressbar",
            troughcolor=BG_PANEL, background=ACCENT_PURP, borderwidth=0, thickness=22)
        pb = ttk.Progressbar(parent, style="Arcane.Horizontal.TProgressbar",
            orient="horizontal", mode="determinate")
        pb.pack(fill="x", padx=20, pady=6)
        return pb

    def _log_write(self, box, msg):
        def _do():
            box.config(state="normal")
            box.insert("end", msg + "\n")
            box.see("end")
            box.config(state="disabled")
        self.after(0, _do)

    def _set_status(self, msg):
        self.after(0, lambda: self.status_var.set(msg))

    # ── TAB: BACKUP ─────────────────────────────────────

    def _build_tab_backup(self):
        p = self.tab_backup

        sec = self._section(p, "🔮  Backup Configuration")
        sec.columnconfigure(1, weight=1)

        self._label(sec, "Forum Section URL:").grid(row=0, column=0, sticky="w", padx=14, pady=10)
        self.bu_url = tk.StringVar()
        self._entry(sec, self.bu_url, width=52).grid(row=0, column=1, columnspan=2, sticky="ew", padx=14, pady=10)

        self._label(sec, "Output Folder:").grid(row=1, column=0, sticky="w", padx=14, pady=10)
        self.bu_outdir = tk.StringVar(value="backup_forum")
        self._entry(sec, self.bu_outdir, width=40).grid(row=1, column=1, sticky="ew", padx=14, pady=10)
        self._btn(sec, "📁  Browse", self._pick_bu_dir, BORDER_GLOW).grid(row=1, column=2, padx=10, pady=10)

        row2 = tk.Frame(sec, bg=BG_MID)
        row2.grid(row=2, column=0, columnspan=3, sticky="ew", padx=14, pady=8)
        self._label(row2, "Start Page:").pack(side="left", padx=(0,8))
        self.bu_startpage = tk.IntVar(value=1)
        self._spinbox(row2, 1, 9999, self.bu_startpage, width=6).pack(side="left")
        self._label(row2, "    Delay (sec):").pack(side="left", padx=(18,8))
        self.bu_delay = tk.DoubleVar(value=0.5)
        self._spinbox(row2, 0.1, 10.0, self.bu_delay, width=6, increment=0.1).pack(side="left")
        self._label(row2, "    Workers:").pack(side="left", padx=(18,8))
        self.bu_workers = tk.IntVar(value=8)
        self._spinbox(row2, 1, 64, self.bu_workers, width=5).pack(side="left")

        # ── Media download option ──
        opt_frame = tk.Frame(sec, bg=BG_MID)
        opt_frame.grid(row=3, column=0, columnspan=3, sticky="ew", padx=14, pady=8)
        self.bu_media = tk.BooleanVar(value=False)
        self._checkbox(opt_frame, "  📥  Also download images, videos & all media files", self.bu_media).pack(side="left")

        bf = tk.Frame(p, bg=BG_MID)
        bf.pack(pady=12)
        self._btn(bf, "⚡   START BACKUP", self._start_backup, ACCENT_PURP).pack(side="left", padx=12)
        self._btn(bf, "⏹   STOP", self._stop_operation, RUNE_RED).pack(side="left", padx=12)

        self.bu_progress = self._progressbar(p)
        self.bu_log      = self._logbox(p, height=10)

    def _pick_bu_dir(self):
        d = filedialog.askdirectory(title="Choose backup folder")
        if d: self.bu_outdir.set(d)

    def _start_backup(self):
        url = self.bu_url.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter the forum section URL!")
            return
        self._stop_event.clear()
        self.bu_progress["value"] = 0
        self._log_write(self.bu_log, "=" * 65)
        self._log_write(self.bu_log, "✨ Backup ritual initiated...")
        if self.bu_media.get():
            self._log_write(self.bu_log, "📥 Media download: ENABLED")
        self._set_status("🔮   Backup in progress...")

        def run():
            backup = VBulletinBackup(
                base_url=url,
                output_dir=self.bu_outdir.get(),
                delay=self.bu_delay.get(),
                max_workers=self.bu_workers.get(),
                start_page=self.bu_startpage.get(),
                log_callback=lambda m: self._log_write(self.bu_log, m),
                download_media=self.bu_media.get(),
                stop_event=self._stop_event,
            )
            self._backup_obj = backup
            def on_progress(done, total):
                pct = (done/total*100) if total else 0
                self.after(0, lambda: self.bu_progress.configure(value=pct))
            result = backup.run_backup(progress_callback=on_progress)
            self._set_status(f"✅   Backup complete — {result} threads downloaded")
            self.after(0, lambda: self.bu_progress.configure(value=100))

        threading.Thread(target=run, daemon=True).start()

    # ── TAB: CONVERT ────────────────────────────────────

    def _build_tab_convert(self):
        p = self.tab_convert

        sec = self._section(p, "📜  HTML Grimoire Settings")
        sec.columnconfigure(1, weight=1)

        self._label(sec, "HTML Source Folder:").grid(row=0, column=0, sticky="w", padx=14, pady=10)
        self.co_indir = tk.StringVar()
        self._entry(sec, self.co_indir, width=40).grid(row=0, column=1, sticky="ew", padx=14, pady=10)
        self._btn(sec, "📁  Browse", self._pick_co_indir, BORDER_GLOW).grid(row=0, column=2, padx=10, pady=10)

        self._label(sec, "Output File (.html):").grid(row=1, column=0, sticky="w", padx=14, pady=10)
        self.co_outfile = tk.StringVar(value="forum_archive.html")
        self._entry(sec, self.co_outfile, width=40).grid(row=1, column=1, sticky="ew", padx=14, pady=10)
        self._btn(sec, "💾  Save As", self._pick_co_outfile, BORDER_GLOW).grid(row=1, column=2, padx=10, pady=10)

        # options
        opt_frame = tk.Frame(sec, bg=BG_MID)
        opt_frame.grid(row=2, column=0, columnspan=3, sticky="ew", padx=14, pady=8)
        self.co_embed = tk.BooleanVar(value=False)
        self._checkbox(opt_frame,
            "  🖼  Embed media as Base64 (self-contained file — may be large)",
            self.co_embed).pack(side="left")

        bf = tk.Frame(p, bg=BG_MID)
        bf.pack(pady=12)
        self._btn(bf, "🌀   CREATE HTML GRIMOIRE", self._start_convert, ACCENT_PURP).pack(side="left", padx=12)
        self._btn(bf, "⏹   STOP", self._stop_operation, RUNE_RED).pack(side="left", padx=12)

        self.co_progress = self._progressbar(p)
        self.co_log      = self._logbox(p, height=12)

    def _pick_co_indir(self):
        d = filedialog.askdirectory(title="Choose folder containing HTML files")
        if d: self.co_indir.set(d)

    def _pick_co_outfile(self):
        f = filedialog.asksaveasfilename(
            title="Save HTML archive", defaultextension=".html",
            filetypes=[("HTML files", "*.html"), ("All files", "*.*")])
        if f: self.co_outfile.set(f)

    def _start_convert(self):
        indir   = self.co_indir.get().strip()
        outfile = self.co_outfile.get().strip()
        if not indir:
            messagebox.showwarning("Warning", "Please choose the HTML source folder!"); return
        if not outfile:
            messagebox.showwarning("Warning", "Please specify an output file!"); return
        self._stop_event.clear()
        self.co_progress["value"] = 0
        self._log_write(self.co_log, "=" * 65)
        self._log_write(self.co_log, "🌀 Weaving the HTML grimoire...")
        if self.co_embed.get():
            self._log_write(self.co_log, "🖼  Base64 embedding: ENABLED (file may be large)")
        self._set_status("📜   Conversion in progress...")

        def run():
            # build MediaDownloader so we can resolve local media
            media_dl = MediaDownloader(indir,
                log_callback=lambda m: self._log_write(self.co_log, m),
                stop_event=self._stop_event) if self.co_embed.get() else None

            def on_progress(done, total):
                pct = (done/total*100) if total else 0
                self.after(0, lambda: self.co_progress.configure(value=pct))

            result = convert_html_folder(
                input_dir=indir,
                output_file=outfile,
                log_callback=lambda m: self._log_write(self.co_log, m),
                progress_callback=on_progress,
                stop_event=self._stop_event,
                media_dl=media_dl,
                embed_base64=self.co_embed.get(),
            )
            self._set_status(f"✅   Grimoire sealed — {result} threads archived")
            self.after(0, lambda: self.co_progress.configure(value=100))

        threading.Thread(target=run, daemon=True).start()

    # ── TAB: FULL OPERATION ─────────────────────────────

    def _build_tab_fullop(self):
        p = self.tab_fullop

        sec = self._section(p, "⚡  Automatic Backup + Conversion")
        sec.columnconfigure(1, weight=1)

        self._label(sec, "Forum Section URL:").grid(row=0, column=0, sticky="w", padx=14, pady=10)
        self.fu_url = tk.StringVar()
        self._entry(sec, self.fu_url, width=52).grid(row=0, column=1, columnspan=2, sticky="ew", padx=14, pady=10)

        self._label(sec, "Output Folder:").grid(row=1, column=0, sticky="w", padx=14, pady=10)
        self.fu_outdir = tk.StringVar(value="backup_forum")
        self._entry(sec, self.fu_outdir, width=40).grid(row=1, column=1, sticky="ew", padx=14, pady=10)
        self._btn(sec, "📁  Browse", self._pick_fu_dir, BORDER_GLOW).grid(row=1, column=2, padx=10, pady=10)

        self._label(sec, "HTML Output File:").grid(row=2, column=0, sticky="w", padx=14, pady=10)
        self.fu_outfile = tk.StringVar(value="forum_archive.html")
        self._entry(sec, self.fu_outfile, width=40).grid(row=2, column=1, sticky="ew", padx=14, pady=10)
        self._btn(sec, "💾  Save As", self._pick_fu_outfile, BORDER_GLOW).grid(row=2, column=2, padx=10, pady=10)

        row_extra = tk.Frame(sec, bg=BG_MID)
        row_extra.grid(row=3, column=0, columnspan=3, sticky="ew", padx=14, pady=8)
        self._label(row_extra, "Start Page:").pack(side="left", padx=(0,8))
        self.fu_startpage = tk.IntVar(value=1)
        self._spinbox(row_extra, 1, 9999, self.fu_startpage, width=6).pack(side="left")
        self._label(row_extra, "    Delay (sec):").pack(side="left", padx=(18,8))
        self.fu_delay = tk.DoubleVar(value=0.5)
        self._spinbox(row_extra, 0.1, 10.0, self.fu_delay, width=6, increment=0.1).pack(side="left")
        self._label(row_extra, "    Workers:").pack(side="left", padx=(18,8))
        self.fu_workers = tk.IntVar(value=8)
        self._spinbox(row_extra, 1, 64, self.fu_workers, width=5).pack(side="left")

        # options
        opt_frame = tk.Frame(sec, bg=BG_MID)
        opt_frame.grid(row=4, column=0, columnspan=3, sticky="ew", padx=14, pady=4)
        self.fu_media  = tk.BooleanVar(value=False)
        self.fu_embed  = tk.BooleanVar(value=False)
        self._checkbox(opt_frame, "  📥  Download media files", self.fu_media).pack(side="left", padx=(0,24))
        self._checkbox(opt_frame, "  🖼  Embed media as Base64 in HTML", self.fu_embed).pack(side="left")

        bf = tk.Frame(p, bg=BG_MID)
        bf.pack(pady=10)
        self._btn(bf, "⚡   BACKUP + CONVERT", self._start_fullop, "#4a1f7a").pack(side="left", padx=12)
        self._btn(bf, "⏹   STOP", self._stop_operation, RUNE_RED).pack(side="left", padx=12)

        phase_frame = tk.Frame(p, bg=BG_MID)
        phase_frame.pack(anchor="w", padx=20, pady=4)
        tk.Label(phase_frame, text="Phase:  ", bg=BG_MID, fg=TEXT_DIM, font=self.font_label).pack(side="left")
        self.fu_phase_var = tk.StringVar(value="Waiting for the ritual...")
        tk.Label(phase_frame, textvariable=self.fu_phase_var,
            bg=BG_MID, fg=ACCENT_GOLD, font=self.font_phase).pack(side="left")

        self.fu_progress = self._progressbar(p)
        self.fu_log      = self._logbox(p, height=9)

    def _pick_fu_dir(self):
        d = filedialog.askdirectory(title="Choose output folder")
        if d: self.fu_outdir.set(d)

    def _pick_fu_outfile(self):
        f = filedialog.asksaveasfilename(
            title="Save HTML archive", defaultextension=".html",
            filetypes=[("HTML files", "*.html"), ("All files", "*.*")])
        if f: self.fu_outfile.set(f)

    def _start_fullop(self):
        url     = self.fu_url.get().strip()
        outdir  = self.fu_outdir.get().strip()
        outfile = self.fu_outfile.get().strip()
        if not url:
            messagebox.showwarning("Warning", "Please enter the forum section URL!"); return
        self._stop_event.clear()
        self.fu_progress["value"] = 0
        self._log_write(self.fu_log, "=" * 65)
        self._log_write(self.fu_log, "✨ Full ritual initiated: Backup + Conversion")

        embed_b64 = self.fu_embed.get()
        dl_media  = self.fu_media.get() or embed_b64   # embedding implies downloading

        def run():
            # ── Phase 1: Backup ──
            self.after(0, lambda: self.fu_phase_var.set("🔮  Phase 1/2 — Downloading Forum..."))
            self._set_status("🔮   Phase 1/2: Backup in progress...")

            backup = VBulletinBackup(
                base_url=url,
                output_dir=outdir,
                delay=self.fu_delay.get(),
                max_workers=self.fu_workers.get(),
                start_page=self.fu_startpage.get(),
                log_callback=lambda m: self._log_write(self.fu_log, m),
                download_media=dl_media,
                stop_event=self._stop_event,
            )
            self._backup_obj = backup

            def on_progress_bu(done, total):
                pct = (done/total*50) if total else 0
                self.after(0, lambda: self.fu_progress.configure(value=pct))

            backup_count = backup.run_backup(progress_callback=on_progress_bu)

            if self._stop_event.is_set():
                self._set_status("⏹  Operation stopped."); return

            # ── Phase 2: Conversion ──
            self.after(0, lambda: self.fu_phase_var.set("📜  Phase 2/2 — Weaving HTML Grimoire..."))
            self._set_status("📜   Phase 2/2: Conversion in progress...")

            media_dl = MediaDownloader(outdir,
                log_callback=lambda m: self._log_write(self.fu_log, m),
                stop_event=self._stop_event) if embed_b64 else None

            def on_progress_co(done, total):
                pct = 50 + (done/total*50) if total else 50
                self.after(0, lambda: self.fu_progress.configure(value=pct))

            convert_count = convert_html_folder(
                input_dir=outdir,
                output_file=outfile,
                log_callback=lambda m: self._log_write(self.fu_log, m),
                progress_callback=on_progress_co,
                stop_event=self._stop_event,
                media_dl=media_dl,
                embed_base64=embed_b64,
                forum_url=url,
            )

            self.after(0, lambda: self.fu_phase_var.set("✅  Ritual complete — The grimoire is sealed!"))
            self._set_status(f"✅   Done — {backup_count} threads downloaded, {convert_count} archived")
            self.after(0, lambda: self.fu_progress.configure(value=100))

        threading.Thread(target=run, daemon=True).start()

    # ── TAB: RESTORATION RITUAL ─────────────────────────────

    def _build_tab_restore(self):
        p = self.tab_restore

        # ── Decorative top banner ──────────────────────────
        banner = tk.Canvas(p, height=58, bg=BG_DEEP, highlightthickness=0)
        banner.pack(fill="x")
        def _draw_banner(event):
            banner.delete("all")
            w = event.width
            banner.create_text(w//2, 18,
                text="ᚠ ᚢ ᚦ ᚨ ᚱ ᚲ ᚷ ᚹ ᚺ ᚾ ᛁ ᛃ ᛇ ᛈ ᛉ ᛊ ᛏ ᛒ ᛖ ᛗ ᛚ ᛜ ᛞ ᛟ",
                fill=BORDER_GLOW, font=self.font_log, anchor="center")
            banner.create_text(w//2, 40,
                text="✦   RESTORATION RITUAL  —  Reverse Parsing & Data Recovery   ✦",
                fill=ACCENT_GOLD, font=self.font_sub, anchor="center")
        banner.bind("<Configure>", _draw_banner)

        # ── Config section ────────────────────────────────
        sec = tk.LabelFrame(p, text="   ᚨ  Input — Converted HTML Archive File   ",
            bg=BG_DEEP, fg=ACCENT_GOLD, font=self.font_sub,
            bd=1, relief="groove",
            highlightbackground=BORDER_GLOW, highlightthickness=1, labelanchor="nw")
        sec.pack(fill="x", padx=20, pady=10)
        sec.columnconfigure(1, weight=1)

        tk.Label(sec, text="HTML Archive File:", bg=BG_DEEP, fg=TEXT_MAIN,
            font=self.font_label).grid(row=0, column=0, sticky="w", padx=14, pady=12)
        self.re_infile = tk.StringVar()
        tk.Entry(sec, textvariable=self.re_infile, width=46,
            bg=BG_PANEL, fg=ACCENT_TEAL, insertbackground=ACCENT_GOLD,
            relief="flat", bd=8, font=self.font_log
            ).grid(row=0, column=1, sticky="ew", padx=14, pady=12)
        tk.Button(sec, text="📂  Open File",
            command=self._pick_re_infile,
            bg=BORDER_GLOW, fg=TEXT_MAIN,
            activebackground=ACCENT_GOLD, activeforeground=BG_DEEP,
            font=self.font_btn, relief="flat", bd=0,
            padx=18, pady=10, cursor="hand2"
            ).grid(row=0, column=2, padx=10, pady=12)

        tk.Label(sec,
            text="Accepts: the single HTML file generated by this archiver (with or without embedded media).\n"
                 "Output files will be saved in the same folder as the HTML file.",
            bg=BG_DEEP, fg=TEXT_DIM, font=self.font_phase, justify="left", anchor="w"
            ).grid(row=1, column=0, columnspan=3, sticky="ew", padx=14, pady=(0,10))

        # ── Phase label ───────────────────────────────────
        self.re_phase_var = tk.StringVar(value="Awaiting the Archon's command...")
        tk.Label(p, textvariable=self.re_phase_var,
            bg=BG_DEEP, fg=ACCENT_GOLD, font=self.font_phase, anchor="w"
            ).pack(anchor="w", padx=22, pady=(4,0))

        # ── Progress bar ──────────────────────────────────
        re_style = ttk.Style()
        re_style.configure("Restore.Horizontal.TProgressbar",
            troughcolor=BG_PANEL, background=ACCENT_GOLD, borderwidth=0, thickness=22)
        self.re_progress = ttk.Progressbar(p, style="Restore.Horizontal.TProgressbar",
            orient="horizontal", mode="determinate")
        self.re_progress.pack(fill="x", padx=20, pady=6)

        # ── TWO ACTION BUTTONS ────────────────────────────
        btn_sec = tk.LabelFrame(p, text="   ᛊ  Choose Output Format   ",
            bg=BG_DEEP, fg=ACCENT_GOLD, font=self.font_sub,
            bd=1, relief="groove",
            highlightbackground=BORDER_GLOW, highlightthickness=1, labelanchor="nw")
        btn_sec.pack(fill="x", padx=20, pady=8)

        btn_inner = tk.Frame(btn_sec, bg=BG_DEEP)
        btn_inner.pack(pady=14)

        # JSON button — deep violet
        tk.Button(btn_inner,
            text="{ }   Convert to JSON",
            command=self._start_restore_json,
            bg="#2d0b5a", fg=ACCENT_GOLD,
            activebackground=ACCENT_GOLD, activeforeground=BG_DEEP,
            font=self.font_btn, relief="flat", bd=0,
            padx=28, pady=14, cursor="hand2"
            ).pack(side="left", padx=16)

        # CSV button — dark teal
        tk.Button(btn_inner,
            text="⊞   Convert to CSV",
            command=self._start_restore_csv,
            bg="#063a3a", fg=ACCENT_TEAL,
            activebackground=ACCENT_TEAL, activeforeground=BG_DEEP,
            font=self.font_btn, relief="flat", bd=0,
            padx=28, pady=14, cursor="hand2"
            ).pack(side="left", padx=16)

        # STOP button
        tk.Button(btn_inner,
            text="⏹   STOP",
            command=self._stop_operation,
            bg=RUNE_RED, fg=TEXT_MAIN,
            activebackground=ACCENT_GOLD, activeforeground=BG_DEEP,
            font=self.font_btn, relief="flat", bd=0,
            padx=22, pady=14, cursor="hand2"
            ).pack(side="left", padx=16)

        # ── Runic log ─────────────────────────────────────
        tk.Label(p, text="ᛟ  Ritual Inscriptions:", bg=BG_DEEP,
            fg=ACCENT_GOLD, font=self.font_sub, anchor="w"
            ).pack(anchor="w", padx=22, pady=(6,0))

        log_frame = tk.Frame(p, bg=BG_PANEL, bd=1, relief="groove")
        log_frame.pack(fill="both", expand=True, padx=20, pady=6)
        re_sb = tk.Scrollbar(log_frame, bg=BORDER_GLOW, troughcolor=BG_DEEP, activebackground=ACCENT_PURP)
        re_sb.pack(side="right", fill="y")
        self.re_log = tk.Text(log_frame, font=self.font_log,
            bg="#09060f", fg=ACCENT_GOLD,
            insertbackground=ACCENT_GOLD,
            yscrollcommand=re_sb.set,
            state="disabled", bd=0, wrap="word")
        self.re_log.pack(fill="both", expand=True, padx=6, pady=6)
        re_sb.config(command=self.re_log.yview)

        # colour tags
        self.re_log.tag_config("head",  foreground=ACCENT_GOLD,  font=self.font_btn)
        self.re_log.tag_config("ok",    foreground=ACCENT_TEAL)
        self.re_log.tag_config("warn",  foreground=RUNE_RED)
        self.re_log.tag_config("dim",   foreground=TEXT_DIM)
        self.re_log.tag_config("media", foreground=ACCENT_PURP)

        # ── Result summary ────────────────────────────────
        self.re_result_var = tk.StringVar(value="")
        tk.Label(p, textvariable=self.re_result_var,
            bg=BG_DEEP, fg=ACCENT_TEAL, font=self.font_status, anchor="center"
            ).pack(fill="x", padx=20, pady=(2,8))

    # ── Helpers ──────────────────────────────────────────

    def _pick_re_infile(self):
        f = filedialog.askopenfilename(
            title="Select the HTML Archive file",
            filetypes=[("HTML files", "*.html *.htm"), ("All files", "*.*")])
        if f:
            self.re_infile.set(f)

    def _re_log_write(self, msg):
        """Thread-safe runic log with colour tagging."""
        def _do():
            self.re_log.config(state="normal")
            if msg.startswith("  ✅") or msg.startswith("✅"):
                tag = "ok"
            elif msg.startswith("  ⚠") or msg.startswith("⚠"):
                tag = "warn"
            elif msg.startswith("    ✦") or msg.startswith("    📥"):
                tag = "media"
            elif any(msg.startswith(pfx) for pfx in ["ᛟ","ᛊ","ᚠ","ᚱ","ᚨ","✨","🜂"]):
                tag = "head"
            elif "⏹" in msg:
                tag = "warn"
            else:
                tag = "dim"
            self.re_log.insert("end", msg + "\n", tag)
            self.re_log.see("end")
            self.re_log.config(state="disabled")
        self.after(0, _do)

    def _re_validate(self):
        """Validate input file. Returns path or None."""
        path = self.re_infile.get().strip()
        if not path:
            messagebox.showwarning("Warning",
                "Please select the HTML archive file first!")
            return None
        if not os.path.isfile(path):
            messagebox.showerror("Error",
                "The selected path is not a valid file.")
            return None
        if not path.lower().endswith((".html", ".htm")):
            if not messagebox.askyesno("Warning",
                    "The file does not have an .html extension.\nProceed anyway?"):
                return None
        return path

    def _re_parse_phase(self, html_path):
        """
        Parse the HTML file and cache results in self._re_cache.
        Returns True on success.  Must be called from a background thread.
        """
        self._re_cache = None
        self.after(0, lambda: self.re_phase_var.set("ᚱ  Deciphering the pergamenes..."))
        self._re_log_write("=" * 60)
        self._re_log_write(f"🜂  Scroll selected: {os.path.basename(html_path)}")
        self._re_log_write("ᛟ  Materialising data from the void...")

        all_threads, csv_rows, total_posts, recovered_dir = _parse_single_html(
            html_path, self._re_log_write, self._stop_event)

        if self._stop_event.is_set():
            self.after(0, lambda: self.re_phase_var.set("⏹  Ritual interrupted."))
            self._set_status("⏹   Restoration stopped.")
            return False

        if not all_threads:
            self._re_log_write("⚠  No threads could be extracted from this file.")
            self.after(0, lambda: self.re_phase_var.set("⚠  No data found."))
            return False

        self._re_log_write(
            f"  ✦ Parsed {len(all_threads)} thread(s), {total_posts} post(s) total")
        self._re_cache = {
            "all_threads":    all_threads,
            "csv_rows":       csv_rows,
            "total_posts":    total_posts,
            "recovered_dir":  recovered_dir,
            "html_dir":       os.path.dirname(os.path.abspath(html_path)),
        }
        return True

    def _start_restore_json(self):
        html_path = self._re_validate()
        if not html_path: return
        self._stop_event.clear()
        self.re_progress["value"] = 0
        self.re_result_var.set("")
        self._set_status("{ }   JSON conversion in progress...")

        def run():
            ok = self._re_parse_phase(html_path)
            if not ok: return

            self.after(0, lambda: self.re_progress.configure(value=60))
            self.after(0, lambda: self.re_phase_var.set("ᛊ  Inscribing the JSON codex..."))

            cache    = self._re_cache
            out_path = os.path.join(cache["html_dir"], "vbulletin_recovery.json")
            result   = restoration_write_json(
                cache["all_threads"], cache["total_posts"], out_path, self._re_log_write)

            self.after(0, lambda: self.re_progress.configure(value=100))
            if result:
                n = len(cache["all_threads"]); p = cache["total_posts"]
                summary = f"✅   JSON sealed — {n} thread(s), {p} post(s)  →  {os.path.basename(result)}"
                self.after(0, lambda: self.re_phase_var.set("✅  JSON codex sealed — Data ready for the database."))
                self.after(0, lambda: self.re_result_var.set(summary))
                self._set_status(f"✅   JSON complete — {n} threads, {p} posts")
                self._re_log_write(f"✅  Saved: {result}")
                self._re_log_write("ᛟ  Ritual completed: Data ready for the database.")
            else:
                self.after(0, lambda: self.re_phase_var.set("⚠  JSON write failed."))
                self._set_status("⚠   JSON write failed — check the log.")

        threading.Thread(target=run, daemon=True).start()

    def _start_restore_csv(self):
        html_path = self._re_validate()
        if not html_path: return
        self._stop_event.clear()
        self.re_progress["value"] = 0
        self.re_result_var.set("")
        self._set_status("⊞   CSV conversion in progress...")

        def run():
            ok = self._re_parse_phase(html_path)
            if not ok: return

            self.after(0, lambda: self.re_progress.configure(value=60))
            self.after(0, lambda: self.re_phase_var.set("ᚠ  Etching the CSV tablet..."))

            cache    = self._re_cache
            out_path = os.path.join(cache["html_dir"], "vbulletin_recovery.csv")
            result   = restoration_write_csv(
                cache["csv_rows"], out_path, self._re_log_write)

            self.after(0, lambda: self.re_progress.configure(value=100))
            if result:
                n = len(cache["all_threads"]); p = cache["total_posts"]
                summary = f"✅   CSV sealed — {n} thread(s), {p} post(s)  →  {os.path.basename(result)}"
                self.after(0, lambda: self.re_phase_var.set("✅  CSV tablet chiselled — Data ready for the database."))
                self.after(0, lambda: self.re_result_var.set(summary))
                self._set_status(f"✅   CSV complete — {n} threads, {p} posts")
                self._re_log_write(f"✅  Saved: {result}")
                self._re_log_write("ᛟ  Ritual completed: Data ready for the database.")
            else:
                self.after(0, lambda: self.re_phase_var.set("⚠  CSV write failed."))
                self._set_status("⚠   CSV write failed — check the log.")

        threading.Thread(target=run, daemon=True).start()

    # ── TAB: WEBSITE MIRROR ─────────────────────────────────

    def _build_tab_mirror(self):
        p = self.tab_mirror

        sec = self._section(p, "🌐  Website Mirror Configuration")
        sec.columnconfigure(1, weight=1)

        # URL
        self._label(sec, "Website URL:").grid(
            row=0, column=0, sticky="w", padx=14, pady=10)
        self.mi_url = tk.StringVar()
        self._entry(sec, self.mi_url, width=52).grid(
            row=0, column=1, columnspan=2, sticky="ew", padx=14, pady=10)

        # Output folder
        self._label(sec, "Output Folder:").grid(
            row=1, column=0, sticky="w", padx=14, pady=10)
        self.mi_outdir = tk.StringVar(value="mirror")
        self._entry(sec, self.mi_outdir, width=40).grid(
            row=1, column=1, sticky="ew", padx=14, pady=10)
        self._btn(sec, "📁  Browse", self._pick_mi_dir, BORDER_GLOW).grid(
            row=1, column=2, padx=10, pady=10)

        # Options row
        row_opts = tk.Frame(sec, bg=BG_MID)
        row_opts.grid(row=2, column=0, columnspan=3, sticky="ew", padx=14, pady=8)

        self._label(row_opts, "Workers:").pack(side="left", padx=(0, 8))
        self.mi_workers = tk.IntVar(value=8)
        self._spinbox(row_opts, 1, 32, self.mi_workers, width=5).pack(side="left")

        self._label(row_opts, "    Delay (sec):").pack(side="left", padx=(18, 8))
        self.mi_delay = tk.DoubleVar(value=0.5)
        self._spinbox(row_opts, 0.0, 10.0, self.mi_delay, width=6, increment=0.1).pack(side="left")

        # Info
        tk.Label(sec,
            text="Downloads the entire website — HTML pages, images, CSS, JS, media —\n"
                 "and rewrites internal links so the mirror works fully offline.",
            bg=BG_MID, fg=TEXT_DIM, font=self.font_phase, justify="left", anchor="w"
        ).grid(row=3, column=0, columnspan=3, sticky="ew", padx=14, pady=(0, 10))

        # Buttons
        bf = tk.Frame(p, bg=BG_MID)
        bf.pack(pady=12)
        self._btn(bf, "🌐   START MIRROR", self._start_mirror, "#1a3a5c").pack(side="left", padx=12)
        self._btn(bf, "⏹   STOP",          self._stop_mirror,  RUNE_RED ).pack(side="left", padx=12)

        # Counter label
        self.mi_count_var = tk.StringVar(value="")
        tk.Label(p, textvariable=self.mi_count_var,
            bg=BG_MID, fg=ACCENT_GOLD, font=self.font_phase, anchor="w"
        ).pack(anchor="w", padx=22, pady=(0, 4))

        # Indeterminate progress bar (we don't know total pages upfront)
        mi_style = ttk.Style()
        mi_style.configure("Mirror.Horizontal.TProgressbar",
            troughcolor=BG_PANEL, background=ACCENT_TEAL, borderwidth=0, thickness=22)
        self.mi_progress = ttk.Progressbar(p, style="Mirror.Horizontal.TProgressbar",
            orient="horizontal", mode="indeterminate")
        self.mi_progress.pack(fill="x", padx=20, pady=6)

        self.mi_log = self._logbox(p, height=13)

    def _pick_mi_dir(self):
        d = filedialog.askdirectory(title="Choose mirror output folder")
        if d:
            self.mi_outdir.set(d)

    def _stop_mirror(self):
        self._mi_stop.set()
        self._set_status("⏹   Mirror stop requested...")
        self._log_write(self.mi_log, "⏹  Mirror stop requested — finishing current downloads...")
        try:
            self.mi_progress.stop()
        except Exception:
            pass

    def _start_mirror(self):
        url    = self.mi_url.get().strip()
        outdir = self.mi_outdir.get().strip()

        if not url:
            messagebox.showwarning("Warning", "Please enter the website URL!"); return
        if not url.startswith(("http://", "https://")):
            messagebox.showwarning("Warning",
                "URL must start with http:// or https://"); return
        if not outdir:
            messagebox.showwarning("Warning", "Please choose an output folder!"); return

        # Each run gets a fresh stop event so STOP only kills this run
        self._mi_stop = threading.Event()

        self._log_write(self.mi_log, "=" * 65)
        self._log_write(self.mi_log, f"🌐 Starting mirror: {url}")
        self._log_write(self.mi_log, f"📁 Output folder: {outdir}")
        self._log_write(self.mi_log, f"⚙  Workers: {self.mi_workers.get()}  |  Delay: {self.mi_delay.get()}s")
        self.mi_count_var.set("🌐  Crawling…  (0 files downloaded)")
        self.mi_progress.start(12)
        self._set_status("🌐   Website Mirror in progress…")

        def on_progress(n):
            self.after(0, lambda: self.mi_count_var.set(
                f"🌐  Crawling…  {n} file(s) downloaded so far"))

        def run():
            crawler = MirrorCrawler(
                base_url=url,
                output_dir=outdir,
                max_workers=self.mi_workers.get(),
                delay=self.mi_delay.get(),
                log_callback=lambda m: self._log_write(self.mi_log, m),
                stop_event=self._mi_stop,
                progress_callback=on_progress,
            )
            n = crawler.run()

            def _finish():
                self.mi_progress.stop()
                self.mi_progress["value"] = 100
                self.mi_count_var.set(f"✅  Mirror complete — {n} file(s) saved to: {outdir}")

            self.after(0, _finish)

            if self._mi_stop.is_set():
                self._set_status(f"⏹   Mirror stopped — {n} files saved")
                self._log_write(self.mi_log, f"⏹  Stopped. {n} file(s) saved.")
            else:
                self._set_status(f"✅   Mirror complete — {n} files saved to: {outdir}")

        threading.Thread(target=run, daemon=True).start()

    # ── Control ─────────────────────────────────────────

    def _stop_operation(self):
        self._stop_event.set()
        self._set_status("⏹   Stop requested — finishing current task...")
        for box in [self.bu_log, self.co_log, self.fu_log]:
            self._log_write(box, "⏹  Operation stopped by user.")
        try:
            self._re_log_write("⏹  Ritual interrupted by user.")
        except Exception:
            pass

    def _on_close(self):
        self._stop_event.set()
        try:
            if self._rune_initialized:
                self.rune_animator.stop()
        except: pass
        self.destroy()


# ─────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────

def main():
    mp.freeze_support()
    app = ArcaneForumArchiver()
    app.mainloop()

if __name__ == "__main__":
    main()
